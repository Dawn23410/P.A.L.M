@echo off
REM ============================================================
REM  Disconnect ALL mapped network drives
REM ============================================================
echo Current connections:
net use
echo.
echo Disconnecting all ...
net use * /delete /y
echo.
echo Done. If a ghost icon remains, press F5 in Explorer.
echo.
pause
