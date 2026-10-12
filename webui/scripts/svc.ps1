<#
  WebUI 后台服务管理（start / stop / status）
  ==========================================
  设计要点：
    1. 后台常驻：用 Start-Process -WindowStyle Hidden 起独立进程，
       它不属于本 PowerShell 的作业对象，所以本窗口退出后服务照常运行。
    2. 幂等：起服务前先探端口，已在跑就不重复起（避免端口冲突和重复进程）。
    3. 可停止：PID 落到 logs\*.pid；停止时优先按 PID 杀，PID 失效再按端口兜底。
    4. 有日志：后台进程没有控制台，stdout/stderr 全部重定向到 logs\*.log。
    5. 失败可见：脚本用退出码表达成功与否，调用方 .cmd 只在失败时暂停。
  注意：本文件是 UTF-8 with BOM（PowerShell 5.1 无 BOM 会按 ANSI 读，中文会乱）。
#>
param(
  [ValidateSet('start','stop','status')]
  [string]$Action = 'start',
  [switch]$NoBrowser
)

$ErrorActionPreference = 'Continue'

$Root          = Split-Path -Parent $PSScriptRoot
$LogDir        = Join-Path $Root 'logs'
$WebPort       = 5173
$KernelPort    = 10093
$WebPidFile    = Join-Path $LogDir 'webui.pid'
$KernelPidFile = Join-Path $LogDir 'kernel.pid'

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

function Say  { param($m, $c = 'Gray') Write-Host $m -ForegroundColor $c }
function Ok   { param($m) Write-Host $m -ForegroundColor Green }
function Warn { param($m) Write-Host $m -ForegroundColor Yellow }
function Bad  { param($m) Write-Host $m -ForegroundColor Red }

function Test-Port {
  param([int]$Port)
  $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return [bool]$c
}

function Listener-Pid {
  param([int]$Port)
  $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) { return [int]$c.OwningProcess }
  return 0
}

function Wait-Port {
  param([int]$Port, [int]$Seconds = 25)
  for ($i = 0; $i -lt ($Seconds * 2); $i++) {
    if (Test-Port $Port) { return $true }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Find-Node {
  $c = Get-Command node.exe -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  $bases = @(
    (Join-Path $env:USERPROFILE '.workbuddy\binaries\node\versions'),
    (Join-Path $env:USERPROFILE '.workbuddy-ai\binaries\node\versions')
  )
  foreach ($b in $bases) {
    if (-not (Test-Path $b)) { continue }
    $dirs = Get-ChildItem $b -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending
    foreach ($d in $dirs) {
      $exe = Join-Path $d.FullName 'node.exe'
      if (Test-Path $exe) { return $exe }
    }
  }
  return $null
}

# 内核需要 fastapi+uvicorn，逐个候选验证「真能 import 再算数」
function Find-KernelPython {
  $cands = @()
  $c = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($c) { $cands += $c.Source }
  foreach ($v in @('Python312','Python311','Python310','Python39')) {
    $p = Join-Path $env:LOCALAPPDATA ('Programs\Python\' + $v + '\python.exe')
    if (Test-Path $p) { $cands += $p }
  }
  foreach ($p in $cands) {
    $null = & $p -c 'import fastapi, uvicorn' 2>&1
    if ($LASTEXITCODE -eq 0) { return $p }
  }
  return $null
}

# 只要 Python（web 服务兜底用，无依赖要求）
function Find-AnyPython {
  $c = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  foreach ($v in @('Python312','Python311','Python310','Python39')) {
    $p = Join-Path $env:LOCALAPPDATA ('Programs\Python\' + $v + '\python.exe')
    if (Test-Path $p) { return $p }
  }
  $c = Get-Command py.exe -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  return $null
}

function Find-KernelRoot {
  if ($env:WEBUI_KERNEL_ROOT) {
    if (Test-Path (Join-Path $env:WEBUI_KERNEL_ROOT 'palm_llm\server\api.py')) { return $env:WEBUI_KERNEL_ROOT }
  }
  $cands = @(
    'D:\P.A.L.M\核心-检验完成\LLM内核',
    'D:\P.A.L.M\1_Demo_LLM',
    'C:\P.A.L.M\LLM内核'
  )
  foreach ($c in $cands) {
    if (Test-Path (Join-Path $c 'palm_llm\server\api.py')) { return $c }
  }
  return $null
}

# 参数不能叫 -Args —— $Args 是 PowerShell 自动变量，用它当参数名会让
# -ArgumentList 收到空值并报 ParameterBindingValidationException。
#
# 为什么用「包装批处理 + cmd /c」，而不是直接 Start-Process -RedirectStandardOutput：
#   1) 后者的重定向句柄由「运行本脚本的那个 PowerShell」持有。本脚本是启动器，
#      起完服务就退出，句柄一没，子进程写进管道的数据就丢了 ——
#      实测日志恒为 0 字节。用 cmd 的 > / 2> 让子进程直接拿真实文件句柄，
#      与启动器生命周期彻底解耦（Windows 上传统的守护写法）。
#   2) 不直接把带 > 的命令行交给 cmd /c，是因为那要穿两层引号解析（PowerShell
#      先建命令行、cmd 再解析），极易被转义搞坏 —— 实测会导致服务根本没起来。
#      改成先生成包装 .cmd，Start-Process 只传一个无空格路径，稳。
#   代价：记录到的 PID 是 cmd.exe 的，停止时必须 taskkill /T 连子进程一起杀。
function Quote-Arg {
  param([string]$a)
  if ($a -match '\s') { return '"' + $a + '"' }
  return $a
}

function Start-Hidden {
  param(
    [string]$Name,
    [string]$Exe,
    [string[]]$ArgList,
    [string]$WorkDir,
    [string]$OutLog,
    [string]$ErrLog,
    [string]$PidFile,
    [hashtable]$Env
  )
  $line = '"' + $Exe + '"'
  foreach ($a in $ArgList) { $line += ' ' + (Quote-Arg $a) }

  $body = @('@echo off')
  $body += 'cd /d "' + $WorkDir + '"'
  if ($Env) {
    foreach ($k in $Env.Keys) { $body += 'set "' + $k + '=' + $Env[$k] + '"' }
  }
  $body += $line + ' > "' + $OutLog + '" 2> "' + $ErrLog + '"'

  # 批处理按控制台代码页解释，路径可能含中文，写 GBK 最稳
  $wrapper = Join-Path $LogDir ($Name + '.run.cmd')
  $nl = [Environment]::NewLine
  [System.IO.File]::WriteAllText($wrapper, ($body -join $nl) + $nl, [System.Text.Encoding]::GetEncoding(936))

  try {
    $p = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', $wrapper) -WorkingDirectory $WorkDir -WindowStyle Hidden -PassThru
  } catch {
    Say ('  启动进程失败：' + $_.Exception.Message) DarkGray
    return $null
  }
  if ($p) { $p.Id | Set-Content -Path $PidFile -Encoding ASCII }
  return $p
}

function Kill-Tree {
  param([int]$ProcId)
  $null = & taskkill /PID $ProcId /T /F 2>&1
  return ($LASTEXITCODE -eq 0)
}

function Stop-ByPidFile {
  param([string]$PidFile, [string]$Name, [int]$Port)
  $killed = $false
  if (Test-Path $PidFile) {
    $raw = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    $procId = 0
    if ([int]::TryParse($raw, [ref]$procId)) {
      $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
      if ($p) {
        $null = Kill-Tree -ProcId $procId
        Say ('  已停止 ' + $Name + '（进程树 PID ' + $procId + '）')
        $killed = $true
      }
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
  }
  if (Test-Port $Port) {
    $lp = Listener-Pid $Port
    if ($lp -gt 0) {
      $null = Kill-Tree -ProcId $lp
      Say ('  已停止 ' + $Name + '（端口 ' + $Port + ' 上的 PID ' + $lp + '，PID 文件已失效）')
      $killed = $true
    }
  }
  if (-not $killed) { Say ('  ' + $Name + ' 本来就没在跑') }
}

# ============================ start ============================
if ($Action -eq 'start') {
  Say ''
  Say '  ========================================' DarkCyan
  Say '          WebUI 后台服务启动' DarkCyan
  Say '  ========================================' DarkCyan
  Say ''

  $webUp = Test-Port $WebPort
  $kernelUp = Test-Port $KernelPort

  if ($kernelUp) {
    Ok ('  [内核] 已在运行（端口 ' + $KernelPort + '，PID ' + (Listener-Pid $KernelPort) + '）')
  } else {
    $kernelRoot = Find-KernelRoot
    $kpy = Find-KernelPython
    if (-not $kernelRoot) {
      Warn '  [内核] 未找到源码目录，跳过。'
      Say  '         可设环境变量 WEBUI_KERNEL_ROOT 指定内核根目录。' DarkGray
    } elseif (-not $kpy) {
      Warn '  [内核] 没找到带 fastapi/uvicorn 的 Python，跳过。'
    } else {
      $out = Join-Path $LogDir 'kernel.log'
      $err = Join-Path $LogDir 'kernel.err.log'
      $p = Start-Hidden -Name 'kernel' -Exe $kpy -ArgList @('-m','palm_llm.server.api','--port',"$KernelPort") -WorkDir $kernelRoot -OutLog $out -ErrLog $err -PidFile $KernelPidFile -Env @{ PYTHONPATH = $kernelRoot; PYTHONUNBUFFERED = '1' }
      if (Wait-Port $KernelPort 20) {
        Ok ('  [内核] 已启动（端口 ' + $KernelPort + '，PID ' + $p.Id + '）')
      } else {
        Bad ('  [内核] 启动失败，看日志：' + $err)
        Say ('         源码：' + $kernelRoot) DarkGray
      }
    }
  }

  if ($webUp) {
    Ok ('  [前端] 已在运行（端口 ' + $WebPort + '，PID ' + (Listener-Pid $WebPort) + '）')
  } else {
    $node = Find-Node
    $out = Join-Path $LogDir 'webui.log'
    $err = Join-Path $LogDir 'webui.err.log'
    $p = $null
    $runtime = $null
    if ($node -and (Test-Path (Join-Path $Root 'core\devserver.js'))) {
      $runtime = 'Node ' + $node
      Say ('  [前端] 运行时：' + $runtime) DarkGray
      $p = Start-Hidden -Name 'webui' -Exe $node -ArgList @('core\devserver.js', "$WebPort") -WorkDir $Root -OutLog $out -ErrLog $err -PidFile $WebPidFile
    } else {
      $py = Find-AnyPython
      if ($py -and (Test-Path (Join-Path $Root 'core\devserver.py'))) {
        $runtime = 'Python ' + $py
        Say ('  [前端] 运行时：' + $runtime) DarkGray
        $p = Start-Hidden -Name 'webui' -Exe $py -ArgList @('core\devserver.py', "$WebPort", '--no-browser') -WorkDir $Root -OutLog $out -ErrLog $err -PidFile $WebPidFile
      }
    }
    if ($p -and (Wait-Port $WebPort 20)) {
      Ok ('  [前端] 已启动（端口 ' + $WebPort + '，PID ' + $p.Id + '）')
    } elseif ($runtime) {
      Bad ('  [前端] 启动失败（' + $runtime + '），看日志：' + $err)
      exit 1
    } else {
      Bad '  [前端] 没找到 Node.js 或 Python，无法启动本地服务。'
      Say '         安装其一下载：https://nodejs.org/ 或 https://www.python.org/downloads/' DarkGray
      exit 1
    }
  }

  Say ''
  Ok  ('  已就绪 → http://localhost:' + $WebPort + '/')
  Say ('  日志目录：' + $LogDir) DarkGray
  Say '  停止服务：双击 停止WebUI.cmd' DarkGray
  Say ''

  if (-not $NoBrowser) { Start-Process ('http://localhost:' + $WebPort + '/') | Out-Null }
  exit 0
}

# ============================ stop ============================
if ($Action -eq 'stop') {
  Say ''
  Say '  正在停止 WebUI 服务…' DarkCyan
  Say ''
  Stop-ByPidFile -PidFile $WebPidFile    -Name '前端' -Port $WebPort
  Stop-ByPidFile -PidFile $KernelPidFile -Name '内核' -Port $KernelPort
  Start-Sleep -Milliseconds 800
  Say ''
  $anyLeft = (Test-Port $WebPort) -or (Test-Port $KernelPort)
  if ($anyLeft) { Warn '  仍有端口在监听，可能被其他程序占用。' }
  else { Ok '  已全部停止。' }
  Say ''
  exit 0
}

# ============================ status ============================
if ($Action -eq 'status') {
  Say ''
  Say '  WebUI 服务状态' DarkCyan
  Say '  ----------------------------------------'
  $svcs = @(
    @{ Name='前端'; Port=$WebPort;    Log='webui.log';  ErrLog='webui.err.log' },
    @{ Name='内核'; Port=$KernelPort; Log='kernel.log'; ErrLog='kernel.err.log' }
  )
  foreach ($svc in $svcs) {
    $up = Test-Port $svc.Port
    $mark = '[已停止]'
    $color = 'DarkGray'
    $extra = ''
    if ($up) {
      $mark = '[运行中]'
      $color = 'Green'
      $extra = '  PID ' + (Listener-Pid $svc.Port)
    }
    Write-Host ('  ' + $svc.Name + '  ' + $svc.Port + '  ') -NoNewline
    Write-Host ($mark + $extra) -ForegroundColor $color
    foreach ($f in @($svc.Log, $svc.ErrLog)) {
      $fp = Join-Path $LogDir $f
      if (Test-Path $fp) {
        $size = [math]::Round((Get-Item $fp).Length / 1KB, 1)
        Say ('        日志 ' + $f + '  ' + $size + ' KB') DarkGray
      }
    }
  }
  Say '  ----------------------------------------'
  Say ('  访问地址：http://localhost:' + $WebPort + '/')
  Say ('  日志目录：' + $LogDir)
  Say ''
  exit 0
}
