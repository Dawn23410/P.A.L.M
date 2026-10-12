@echo off
chcp 936 >nul
title WebUI 状态
cd /d "%~dp0"

rem 查看两个服务的运行状态、PID 与日志大小。

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\svc.ps1" -Action status
echo.
echo   按任意键关闭。
pause >nul
exit /b
