@echo off
title P.A.L.M Frontend Preview (:43210)
cd /d "%~dp0"
echo ============================================================
echo  P.A.L.M Frontend  -  vite preview (static, instant) :43210
echo  (Minimize this window. Closing it stops the frontend.)
echo ============================================================
where node >nul 2>&1 || (echo [error] Node.js not found. Install from https://nodejs.org/ && exit /b)
if not exist "%~dp0node_modules" (
  echo [%TIME%] First run: npm install...
  call npm install
  if errorlevel 1 (echo [error] npm install failed. && exit /b)
)
if not exist "%~dp0dist\index.html" (
  echo [%TIME%] No dist found, running build first (one-time, ~30-60s)...
  call npm run build
  if errorlevel 1 (echo [error] build failed. && exit /b)
)
if /i "%~1"=="/rebuild" (
  echo [%TIME%] /rebuild requested, running build...
  call npm run build
  if errorlevel 1 (echo [error] build failed. && exit /b)
)
echo [%TIME%] Starting vite preview (static server, opens instantly)...
call npm run preview -- --port 43210 --strictPort
echo [%TIME%] Frontend preview exited.
