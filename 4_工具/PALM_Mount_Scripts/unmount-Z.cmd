@echo off
net use Z: /delete /y >nul 2>&1
net use * /delete /y >nul 2>&1
echo   Z: disconnected.
pause
