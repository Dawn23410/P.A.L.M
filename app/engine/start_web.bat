@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "VPY=%~dp0.venv\Scripts\python.exe"
if not exist ".venv" (
    echo 正在创建虚拟环境...
    py -3 -m venv .venv || python -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install -r requirements.txt -q >nul 2>&1
echo 启动 AI 对话 Web UI (http://127.0.0.1:8080) ...
start "AI-Chat-Web" "%VPY%" web.py --port 8080
timeout /t 2 >nul
start "" "http://127.0.0.1:8080/"
exit /b
