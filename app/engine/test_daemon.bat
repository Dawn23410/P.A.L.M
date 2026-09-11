@echo off
chcp 65001 >nul
title P.A.L.M 常驻测试 (pythonw)
setlocal

REM ============================================================
REM  临时后台常驻测试（不注册服务、不改开机启动）
REM  ------------------------------------------------------------
REM  用 pythonw 拉起 engine/web.py，无控制台窗口常驻。
REM  仅用于验证 "后台常驻" 可行性，进程在用户注销/重启后不保留。
REM  停止请用 stop_daemon.bat 或任务管理器结束 pythonw。
REM ============================================================

set "ENGINE_DIR=%~dp0"
set "VPY=%ENGINE_DIR%.venv\Scripts\pythonw.exe"
set "SCRIPT=%ENGINE_DIR%web.py"

if not exist "%VPY%" (
    echo [错误] 未找到 pythonw: %VPY%
    pause & exit /b 1
)

echo 正在以 pythonw 后台启动 engine/web.py (http://127.0.0.1:8080) ...
start "PALM-Engine-Test" /min "%VPY%" "%SCRIPT%" "--host" "127.0.0.1" "--port" "8080"
timeout /t 3 >nul
echo 已启动。验证: curl http://127.0.0.1:8080/
echo 停止: 运行 stop_daemon.bat 或结束 pythonw 进程。
