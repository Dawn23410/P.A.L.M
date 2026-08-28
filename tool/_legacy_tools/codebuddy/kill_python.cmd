@echo off
echo Killing python processes...
taskkill /f /im python.exe 2>nul
taskkill /f /im pythonw.exe 2>nul
echo Done.
pause
