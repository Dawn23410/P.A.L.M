@echo off
REM ============================================================
REM  PALM cloud drive -> mount account 321803 as Z:
REM  Unified share : \\192.168.20.252\palm
REM  Credential    : determines WHICH account you land in
REM ============================================================
setlocal
set ACC=321803
set PW=[REDACTED_PASSWORD]
set SRV=\\192.168.20.252\palm

echo [1/3] clearing existing network connections ...
net use * /delete /y >nul 2>&1

echo [2/3] mounting %SRV%  as  Z:   [user=%ACC%] ...
net use Z: %SRV% %PW% /user:%ACC% /persistent:yes
if errorlevel 1 (
  echo.
  echo   [FAILED] Check: same LAN?  account/password correct?
  echo.
  pause
  exit /b 1
)

echo [3/3] done.
echo.
echo   Z:  ==^>  %SRV%     as user %ACC%
echo   Inside, the shared folder starts with "1-" (rename/delete disabled)
echo.
pause
endlocal
