@echo off
chcp 936 >nul

REM ============================================================
REM  P.A.L.M One-Click Launcher (Master Launcher)
REM  Encoding: pure ASCII (no Chinese) to avoid GBK/UTF-8 corruption.
REM  Usage: double-click -> one-click launch (backend+frontend+voice+cosy+auto browser).
REM          For menu: run this bat with /menu
REM  Design: services run HIDDEN via PowerShell Start-Process -WindowStyle Hidden.
REM          Start-Process spawns fully detached (orphan) processes, so they
REM          keep running after this window closes and nothing pops up.
REM          Status/logs: %TEMP%\palm_*.log  and  %TEMP%\palm_status.log
REM  Modes:  default = dev (hot-reload, slower cold start ~30-90s)
REM          menu [5] = prod preview (build+static serve, opens instantly)
REM ============================================================

set "ROOT=%~dp0"
cd /d "%ROOT%"
set "ENGINE=%ROOT%engine"
set "FRONTEND=%ROOT%ui\migrated-frontend"
set "PACKAGES=%ROOT%tool\_legacy_tools\codebuddy\runtime"
REM [removed] set "VOICE=%ROOT%speech\gpt-sovits"
REM [removed] set "COSY=%ROOT%speech\cosyvoice"
set "VOSK=%ROOT%..\P.A.L.M\����ʶ��"
set "VOSK_LOG=%TEMP%\palm_vosk.log"
REM [removed] set "MENTALCORE=%ROOT%..\P.A.L.M\���Ǻ���"
REM [removed] set "MENTALCORE_LOG=%TEMP%\palm_mentalcore.log"
set "WEAVE_LOG=%TEMP%\palm_weave.log"

if not defined TEMP set "TEMP=%USERPROFILE%\AppData\Local\Temp"
if not exist "%TEMP%\" mkdir "%TEMP%" >nul 2>&1
set "LAUNCH_LOG=%TEMP%\palm_launch.log"
set "BACKEND_LOG=%TEMP%\palm_backend.log"
set "FRONTEND_LOG=%TEMP%\palm_frontend.log"
set "PACKAGES_LOG=%TEMP%\palm_packages.log"
REM [removed] set "VOICE_LOG=%TEMP%\palm_voice.log"
REM [removed] set "COSY_LOG=%TEMP%\palm_cosy.log"
set "STATUS_LOG=%TEMP%\palm_status.log"
echo ===== P.A.L.M launch log %DATE% %TIME% ===== > "%LAUNCH_LOG%"

if /i "%~1"=="/menu" (goto :menu) else (goto :all)

:log
if not defined LAUNCH_LOG set "LAUNCH_LOG=%TEMP%\palm_launch.log"
echo [%TIME%] %* >> "%LAUNCH_LOG%"
goto :eof

REM ---------- hidden launcher (no cmd window) ----------
REM %1 = absolute wrapper path, %2 = absolute log path.
REM Paths contain no spaces, so no inner quotes are needed inside cmd /c.
REM Start-Process creates a DETACHED process; the hidden PowerShell that
REM spawns it exits immediately but the service keeps running.
:launch_hidden
call :log "launch_hidden: %~1 -> %~2"
if not exist "%~1" (
    echo  [error] Missing %~1
    call :log "launch_hidden: wrapper missing"
    goto :eof
)
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c %~1 >> %~2 2>&1' -WindowStyle Hidden"
call :log "launch_hidden: done"
goto :eof

REM ---------- kill leftover by port (enum only, EDR-safe) ----------
:kill_ports
echo  Cleaning leftover processes on ports 8080 / 43210 / 5000 / 9880 / 7861 / 2700 / 7788 / 7799 ...
call :kill_one 8080
call :kill_one 43210
call :kill_one 5000
call :kill_one 9880
call :kill_one 7861
call :kill_one 2700
call :kill_one 7788
call :kill_one 7799
goto :eof

:kill_one
for /f "usebackq tokens=*" %%p in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %1 -State Listen -ErrorAction SilentlyContinue).OwningProcess"`) do (
    if not "%%p"=="" (
        echo     Killing PID %%p on port %1
        call :log "kill port %1 PID %%p"
        taskkill /PID %%p /F >nul 2>&1
    )
)
goto :eof

REM ---------- open browser only AFTER port 43210 is listening ----------
REM Polls up to 180s so the page is actually ready when the browser opens,
REM instead of showing a blank screen during Vite's cold start.
:open_browser
call :log "open_browser: waiting for port 43210..."
powershell -NoProfile -WindowStyle Hidden -Command "$p=43210; $ok=$false; for($i=0;$i-lt180;$i++){ try { if(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue){ $ok=$true; break } } catch {}; Start-Sleep -Seconds 1 }; if($ok){ Start-Process 'http://localhost:43210' } else { Write-Host 'frontend port 43210 not ready in 180s' }"
goto :eof

REM ---------- menu ----------
:menu
cls
echo.
echo  ============================================================
echo              P.A.L.M  One-Click Launcher
echo  ============================================================
echo.
REM [removed] echo   [1] One-click  =  backend + frontend（dev） + voice + cosy + auto browser
echo   [2] Backend only   （web.py, port 8080）
echo   [3] Frontend only  （vite dev, port 43210）
echo   [4] Stop backend
echo   [5] Prod preview   （build+static serve, opens INSTANTLY - for daily operation）
echo   [0] Exit
echo.
set /p CH=Enter choice （Enter=1）:
if "%CH%"=="" set "CH=1"
if "%CH%"=="1" goto all
if "%CH%"=="2" call :launch_hidden "%ENGINE%\run_backend.bat" "%BACKEND_LOG%" & goto menu
if "%CH%"=="3" call :launch_hidden "%FRONTEND%\run_frontend.bat" "%FRONTEND_LOG%" & goto menu
if "%CH%"=="4" call :stop_backend & goto menu
if "%CH%"=="5" goto prod
if "%CH%"=="0" exit /b
echo.
echo  [!] Invalid choice, try again.
pause
goto menu

REM ---------- one-click (dev mode) ----------
:all
cls
call :log "===== all: start one-click launch (dev) ====="
echo  ============================================================
REM [removed] echo     One-click: backend + frontend（dev） + voice + cosy + auto browser
echo  ============================================================
echo.
echo  [hint] Double-click = one-click （no input）. For menu, run with /menu
echo  [mode] DEV - frontend has hot-reload but a slower cold start （~30-90s）.
echo         For instant open use menu [5] Prod preview.
echo  [logs] backend : %BACKEND_LOG%
echo         frontend: %FRONTEND_LOG%
echo         packages: %PACKAGES_LOG%
REM [removed] echo         voice    : %VOICE_LOG%
REM [removed] echo         cosy     : %COSY_LOG%
echo         vosk     : %VOSK_LOG%
REM [removed] echo         mentalcore: %MENTALCORE_LOG%
echo         weave    : %WEAVE_LOG%
echo         status   : %STATUS_LOG%
echo.
call :kill_ports
echo.
call :launch_hidden "%ENGINE%\run_backend.bat" "%BACKEND_LOG%"
call :launch_hidden "%FRONTEND%\run_frontend.bat" "%FRONTEND_LOG%"
call :launch_hidden "%PACKAGES%\run_packages.bat" "%PACKAGES_LOG%"
REM [removed] call :launch_hidden "%COSY%\run_cosy_api.bat" "%COSY_LOG%"
REM Voice (9880) is heavy (GPU model load). Launch it async and never
REM wait for it - it comes up in its own hidden process after the others.
REM [removed] call :launch_hidden "%VOICE%\run_voice.bat" "%VOICE_LOG%"
call :launch_hidden "%VOSK%\run_server.bat" "%VOSK_LOG%"
REM [removed] call :launch_hidden "%MENTALCORE%\run_bridge.bat" "%MENTALCORE_LOG%"
REM 织语层独立服务（默认本地 Mock，端口 7799）——从心智魔方核心拆出，可选运行。
REM [removed] call :launch_hidden "%MENTALCORE%\run_weave.bat" "%WEAVE_LOG%"
REM Open the browser ONLY after the frontend port is actually listening.
call :open_browser
REM Wait a few seconds, then probe which ports are actually listening.
powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.LocalPort -in 8080,43210,5000,9880,7861,2700,7788,7799} | Select-Object -ExpandProperty LocalPort | Sort-Object -Unique | Out-File '%STATUS_LOG%' -Encoding utf8"
REM [removed] echo  Launched backend + frontend + packages + cosy + voice as HIDDEN background
echo  services （no cmd windows）. Browser opens once the frontend is ready.
REM [removed] echo  Voice （9880） loads models on GPU and may take 30-90s; that is normal.
echo  You may close this window; the services keep running in background.
echo.
echo  [Waiting ~6s for services to bind, then showing listening ports...]
%SystemRoot%\System32\timeout.exe /t 6 /nobreak >nul
echo  ===== Listening ports after launch （from %STATUS_LOG%） =====
if exist "%STATUS_LOG%" (type "%STATUS_LOG%") else (echo   （status not ready yet; check %STATUS_LOG% in a few seconds）)
echo.
echo  [Launcher will auto-close in 8s]
%SystemRoot%\System32\timeout.exe /t 8 /nobreak >nul
exit /b

REM ---------- one-click (prod preview mode: instant open) ----------
:prod
cls
call :log "===== prod: build+preview launch ====="
echo  ============================================================
REM [removed] echo     Prod preview: backend + frontend（preview） + voice + cosy
echo  ============================================================
echo.
echo  [mode] PROD PREVIEW - frontend is built once then served statically,
echo         so it opens INSTANTLY. No hot-reload; rebuild after code changes
echo         （run this bat with /menu, pick [5] after deleting dist, or pass
echo          run_frontend_preview.bat /rebuild）。
echo  [logs] backend : %BACKEND_LOG%
echo         frontend: %FRONTEND_LOG%
echo         packages: %PACKAGES_LOG%
REM [removed] echo         voice    : %VOICE_LOG%
REM [removed] echo         cosy     : %COSY_LOG%
echo         vosk     : %VOSK_LOG%
REM [removed] echo         mentalcore: %MENTALCORE_LOG%
echo         weave    : %WEAVE_LOG%
echo         status   : %STATUS_LOG%
echo.
call :kill_ports
echo.
call :launch_hidden "%ENGINE%\run_backend.bat" "%BACKEND_LOG%"
call :launch_hidden "%FRONTEND%\run_frontend_preview.bat" "%FRONTEND_LOG%"
call :launch_hidden "%PACKAGES%\run_packages.bat" "%PACKAGES_LOG%"
REM [removed] call :launch_hidden "%COSY%\run_cosy_api.bat" "%COSY_LOG%"
REM [removed] call :launch_hidden "%VOICE%\run_voice.bat" "%VOICE_LOG%"
call :launch_hidden "%VOSK%\run_server.bat" "%VOSK_LOG%"
REM [removed] call :launch_hidden "%MENTALCORE%\run_bridge.bat" "%MENTALCORE_LOG%"
REM [removed] call :launch_hidden "%MENTALCORE%\run_weave.bat" "%WEAVE_LOG%"
call :open_browser
powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.LocalPort -in 8080,43210,5000,9880,7861,2700,7788,7799} | Select-Object -ExpandProperty LocalPort | Sort-Object -Unique | Out-File '%STATUS_LOG%' -Encoding utf8"
echo  Launched in PROD PREVIEW mode （frontend opens instantly once ready）.
echo  You may close this window; the services keep running in background.
echo.
echo  [Waiting ~6s for services to bind, then showing listening ports...]
%SystemRoot%\System32\timeout.exe /t 6 /nobreak >nul
echo  ===== Listening ports after launch （from %STATUS_LOG%） =====
if exist "%STATUS_LOG%" (type "%STATUS_LOG%") else (echo   （status not ready yet; check %STATUS_LOG% in a few seconds）)
echo.
echo  [Launcher will auto-close in 8s]
%SystemRoot%\System32\timeout.exe /t 8 /nobreak >nul
exit /b

REM ---------- stop backend ----------
:stop_backend
cls
echo  ============================================================
echo        Stop backend
echo  ============================================================
echo.
echo  Killing backend process on 8080...
call :kill_one 8080
echo  [OK] Done.
pause
goto menu
