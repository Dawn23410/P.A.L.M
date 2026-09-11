@echo off
title P.A.L.M Backend (:8080)
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
echo ============================================================
echo  P.A.L.M Backend  -  web.py on http://127.0.0.1:8080
echo  (Minimize this window. Closing it stops the backend.)
echo ============================================================
echo [%TIME%] Installing/checking dependencies...
"%~dp0.venv\Scripts\pip.exe" install -r "%~dp0requirements.txt" -q
if errorlevel 1 (
  echo [%TIME%] [ERROR] pip install failed. Check the messages above.
  exit /b 1
)
echo [%TIME%] Starting web.py ...
"%~dp0.venv\Scripts\python.exe" web.py --host 127.0.0.1 --port 8080
echo [%TIME%] Backend exited.
