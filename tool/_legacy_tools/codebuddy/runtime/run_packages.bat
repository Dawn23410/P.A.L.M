@echo off
title P.A.L.M GSV Package API (:5000)
cd /d "%~dp0"
set "SYS_PY=C:\Users\Dawn\AppData\Local\Programs\Python\Python310\python.exe"
set "VENV_PY=%~dp0venv\Scripts\python.exe"

REM Self-heal: build the venv on first run (needs network once).
if not exist "%VENV_PY%" (
    echo [%TIME%] [setup] venv missing - building with %SYS_PY% ...
    if not exist "%SYS_PY%" (
        echo [ERROR] System Python 3.10 not found at %SYS_PY%. Install Python 3.10 to enable the package service.
        exit /b 1
    )
    "%SYS_PY%" -m venv "%~dp0venv" || (echo [ERROR] venv creation failed. & exit /b 1)
    "%VENV_PY%" -m pip install -q --upgrade pip fastapi uvicorn pydantic werkzeug || (echo [ERROR] pip install failed (network needed on first run). & exit /b 1)
    echo [%TIME%] [setup] venv ready.
)

echo ============================================================
echo  P.A.L.M GSV Package API  -  http://127.0.0.1:5000
echo  (Minimize this window. Closing it stops the service.)
echo ============================================================
echo [%TIME%] Starting GSV Package API (FastAPI)...
"%VENV_PY%" "%~dp0server_fastapi.py"
echo [%TIME%] Package API exited.
