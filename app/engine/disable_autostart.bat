@echo off
chcp 65001 >nul
title P.A.L.M 取消开机自启
setlocal

set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
set "VALUE=PALM-Autostart"

echo 正在移除开机自启（用户级）...
reg delete "%RUN_KEY%" /V "%VALUE%" /F
if errorlevel 1 (
    echo [提示] 注册项不存在或删除失败
) else (
    echo 已取消 P.A.L.M 开机自启。
)
pause
