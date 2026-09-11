@echo off
chcp 65001 >nul
title P.A.L.M 后台服务注册 (nssm)
setlocal

REM ============================================================
REM  P.A.L.M 后台常驻服务注册脚本
REM  ------------------------------------------------------------
REM  本脚本将 engine/web.py 注册为 Windows 服务，实现：
REM    - 后台无窗口常驻
REM    - 系统级开机自启（登录前即启动，需管理员运行本脚本）
REM    - 崩溃自动重启
REM
REM  注意：本脚本默认【不自动执行】。由运维手动以管理员身份运行。
REM  仅做一次适配/测试时，不需要真正注册，请用 test_daemon.bat 临时验证。
REM
REM  [已就绪] 用户级开机自启：enable_autostart.bat（HKCU Run，免管理员，已验证）
REM  [已就绪] 托盘进程：tray_app.py（系统托盘 + 自动拉起后端）
REM  [已恢复] src/sandbox/net.pyc（3.10）+ ast/threat/honeypot/adjudicator 源码已补齐
REM ============================================================

set "ENGINE_DIR=%~dp0"
set "VPY=%ENGINE_DIR%.venv\Scripts\pythonw.exe"
set "SCRIPT=%ENGINE_DIR%web.py"
set "SERVICE_NAME=PALM-Engine"
set "NSSM=%ENGINE_DIR%tools\nssm.exe"
set "LOG=%ENGINE_DIR%logs\palm-engine.log"

if not exist "%VPY%" (
    echo [错误] 未找到 pythonw: %VPY%
    echo   请先运行 start.bat 创建虚拟环境。
    pause & exit /b 1
)

if not exist "%SCRIPT%" (
    echo [错误] 未找到服务入口: %SCRIPT%
    pause & exit /b 1
)

REM --- 获取 nssm（若本地不存在则提示手动放置） ---
if not exist "%NSSM%" (
    echo [提示] 未找到 nssm: %NSSM%
    echo   请从 https://nssm.cc 下载 nssm.exe（64位）放到 engine\tools\nssm.exe
    echo   或使用系统 sc 命令替代（见文档）。
    pause & exit /b 1
)

if not exist "%ENGINE_DIR%logs" mkdir "%ENGINE_DIR%logs"

echo 正在注册 Windows 服务: %SERVICE_NAME%
"%NSSM%" install %SERVICE_NAME% "%VPY%" "web.py" "--host" "127.0.0.1" "--port" "8080"
"%NSSM%" set %SERVICE_NAME% AppDirectory "%ENGINE_DIR%"
"%NSSM%" set %SERVICE_NAME% DisplayName "P.A.L.M Engine Service"
"%NSSM%" set %SERVICE_NAME% Description "P.A.L.M 后端常驻服务（engine/web.py）"
"%NSSM%" set %SERVICE_NAME% Start SERVICE_AUTO_START
"%NSSM%" set %SERVICE_NAME% AppStdout "%LOG%"
"%NSSM%" set %SERVICE_NAME% AppStderr "%LOG%"
"%NSSM%" set %SERVICE_NAME% AppRotateFiles 1
"%NSSM%" set %SERVICE_NAME% AppRotateBytes 1048576
REM 崩溃后 3 秒内重启
"%NSSM%" set %SERVICE_NAME% AppExit Default Restart
"%NSSM%" set %SERVICE_NAME% AppRestartDelay 3000

echo.
echo 服务已注册。可执行以下命令管理：
echo   启动:  %NSSM% start %SERVICE_NAME%
echo   停止:  %NSSM% stop  %SERVICE_NAME%
echo   卸载:  %NSSM% remove %SERVICE_NAME% confirm
echo   状态:  sc query %SERVICE_NAME%
echo.
echo 开机自启已配置为 SERVICE_AUTO_START（系统级，登录前启动）。
echo 如需立即启动: %NSSM% start %SERVICE_NAME%
pause
