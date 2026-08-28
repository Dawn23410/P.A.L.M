@echo off
chcp 65001 >nul
title P.A.L.M Module Manager

cd /d "%~dp0.."

set "PY_CMD=%~dp0..\runtime\venv\Scripts\python.exe"

echo ========================================
echo   P.A.L.M Module Manager
echo ========================================
echo.
echo Starting API server on http://127.0.0.1:9090 ...
echo.

:: 释放可能残留的 9090 端口
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9090 "') do (
    taskkill /f /pid %%a >nul 2>nul
)

:: 启动模块管理服务
start "P.A.L.M Manager" "%PY_CMD%" -m uvicorn manager.app:app --host 127.0.0.1 --port 9090

echo.
echo API docs: http://127.0.0.1:9090/docs
echo.
pause
