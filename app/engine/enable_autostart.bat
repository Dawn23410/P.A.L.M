@echo off
chcp 65001 >nul
title P.A.L.M 一键开机自启
setlocal

REM ============================================================
REM  P.A.L.M 一键开机自启（用户级，无需管理员）
REM  ------------------------------------------------------------
REM  1) 写入注册表 HKCU\...\Run，下次登录自动运行 tray_app.py
REM  2) 立刻拉起托盘（pythonw 无窗口），托盘会自动启动后端
REM  可逆：运行 disable_autostart.bat 取消
REM  托盘右键菜单也有「☐/☑ 开机自启」可随时开关
REM ============================================================

set "ENGINE_DIR=%~dp0"
set "VPY=%ENGINE_DIR%.venv\Scripts\pythonw.exe"
set "TRAY=%ENGINE_DIR%tray_app.py"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
set "VALUE=PALM-Autostart"

if not exist "%VPY%" (
    echo [错误] 未找到 pythonw: %VPY%
    pause & exit /b 1
)

echo [1/2] 注册开机自启（用户级）...
reg add "%RUN_KEY%" /V "%VALUE%" /T REG_SZ /D "\"%VPY%\" \"%TRAY%\"" /F
if errorlevel 1 (
    echo [失败] 写入注册表出错
    pause & exit /b 1
)

echo [2/2] 立即启动托盘（后端将随之常驻）...
start "" "%VPY%" "%TRAY%"

echo.
echo 完成！当前已：
echo   - 注册开机自启（下次登录自动运行）
echo   - 托盘已在后台运行，后端自动拉起 (http://127.0.0.1:8080)
echo   - 双击托盘图标打开控制台；右键可开关「开机自启」
echo.
echo 取消自启：运行 disable_autostart.bat
pause
