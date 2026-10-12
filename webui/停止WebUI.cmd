@echo off
chcp 936 >nul
title WebUI 停止
cd /d "%~dp0"

rem 停掉后台常驻的内核与前端服务（先按 PID 文件，失效再按端口兜底）。

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\svc.ps1" -Action stop
echo.
echo   按任意键关闭。
pause >nul
exit /b
