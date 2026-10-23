@echo off
REM PALM pre-reinstall backup -> NAS (Z:)
echo Backing up to Z:\_backup_20261009 ...
echo Progress log: C:\Users\24459\Desktop\PALM_Backup\backup.log
echo.
"C:\Users\24459\.workbuddy-ai\binaries\python\versions\3.13.12\python.exe" "C:\Users\24459\Desktop\PALM_Backup\backup.py"
echo.
echo Done. Exit code = %ERRORLEVEL%
pause
