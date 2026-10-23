@echo off
REM ============================================================
REM  Mount the UNIFIED share, asking for credentials.
REM  Same address every time - the account name decides where you land.
REM ============================================================
setlocal
set SRV=\\192.168.20.252\palm
echo Available accounts: [REDACTED_ACCOUNT] / 321801 / 321802 / 321803 / 321804 / 321805
echo.
set /p ACC=Account name : 
if "%ACC%"=="" ( echo No account entered. & pause & exit /b 1 )
set /p PW=Password (Enter = [REDACTED_PASSWORD]) : 
if "%PW%"=="" set PW=[REDACTED_PASSWORD]

echo.
echo [1/2] clearing existing network connections ...
net use * /delete /y >nul 2>&1
echo [2/2] mounting %SRV% as Z: as user %ACC% ...
net use Z: %SRV% %PW% /user:%ACC% /persistent:yes
if errorlevel 1 ( echo   [FAILED] & pause & exit /b 1 )
echo.
echo   OK -^> Z: is now account %ACC%
echo.
pause
endlocal
