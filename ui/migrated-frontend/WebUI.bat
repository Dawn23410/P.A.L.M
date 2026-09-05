@echo off
title P.A.L.M - WebUI

echo ============================================
echo       P.A.L.M . WebUI
echo ============================================
echo.

cd /d "%~dp0"

echo [1/3] Node.js detect...
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] Node.js not found. Install from https://nodejs.org/
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node --version') do echo   version: %%i
echo [OK]
echo.

echo [2/3] deps check...
if not exist "node_modules\" (
    echo   first run, installing deps...
    call npm install
    if %errorlevel% neq 0 (
        echo [FAIL] npm install error
        pause
        exit /b 1
    )
    echo [OK] deps installed
) else (
    echo [SKIP] deps exist
)
echo.

echo [3/3] starting WebUI...
echo.
echo   URL: http://localhost:43210
echo   press Ctrl+C to stop
echo.

set GENIE_SAFE_DELETE=off
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:43210"
call npx vite --host --port 43210
pause
