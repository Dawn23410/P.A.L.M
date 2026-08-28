@echo off
REM GSV Runtime Server 启动脚本
REM 启动本地 API 服务器，提供整合包管理功能

echo ============================================
echo   GSV Package API Server
echo ============================================
echo.
echo 正在启动服务器...
echo 整合包路径: %~dp0packages
echo 下载路径:   %~dp0downloads
echo.
echo 启动地址: http://127.0.0.1:5000
echo (按 Ctrl+C 停止)
echo.

"%~dp0venv\Scripts\python.exe" "%~dp0server_fastapi.py"
pause
