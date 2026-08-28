@echo off
chcp 65001 >nul
title P.A.L.M 停止常驻测试
setlocal
echo 正在停止 P.A.L.M 常驻测试进程 (pythonw web.py) ...
taskkill /fi "IMAGENAME eq pythonw.exe" /fi "WINDOWTITLE eq PALM-Engine-Test*" >nul 2>&1
taskkill /f /im pythonw.exe >nul 2>&1
echo 已尝试停止。若仍占用 8080，请于任务管理器结束 pythonw.exe。
