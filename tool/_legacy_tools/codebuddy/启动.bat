@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [P.A.L.M] Starting...
echo.

if not exist "node_modules" (
    echo Installing dependencies...
    call npm install || (pause & exit /b 1)
)

set "PY_CMD=%~dp0runtime\venv\Scripts\python.exe"
%PY_CMD% launcher.py

echo.
echo [P.A.L.M] Frontend launched. This window will close...
timeout /t 2 /nobreak >nul
exit
