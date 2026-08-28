@echo off
title P.A.L.M Frontend (:43210)
cd /d "%~dp0"
echo ============================================================
echo  P.A.L.M Frontend  -  vite on http://localhost:43210
echo  (Minimize this window. Closing it stops the frontend.)
echo ============================================================
where node >nul 2>&1 || (echo [error] Node.js not found. Install from https://nodejs.org/ && exit /b)
if not exist "%~dp0node_modules" (
  echo [%TIME%] First run: npm install...
  call npm install
  if errorlevel 1 (echo [error] npm install failed. && exit /b)
)
echo [%TIME%] Starting vite ...
call npm run dev
echo [%TIME%] Frontend exited.
