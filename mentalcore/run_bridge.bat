@echo off
cd /d "%~dp0"
setlocal
rem 心智魔方 · 织语层桥接服务（无窗口常驻由 P.A.L.M一键启动.bat 负责拉起本脚本）
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
rem 兜底安装 mentalcore 运行所需依赖（mock 模式不需要 chromadb，记忆面会自动降级）
"%PY%" -m pip install -q httpx gmssl pydantic 2>nul
"%PY%" "%~dp0bridge.py"
endlocal
