@echo off
chcp 65001 >nul
title 桌面项目启动中心
set "BASE=C:\Users\Dawn\Desktop"

:menu
cls
echo ==================================================
echo              桌面项目启动中心  (Master Launcher)
echo ==================================================
echo.
echo  ---- 项目（点击后在浏览器打开对应 Web UI）----
echo    [1] AI 对话命令行客户端          (ai-chat)      Web: http://127.0.0.1:8080
echo    [2] 沙箱                          (sandbox)      Web: http://127.0.0.1:8081
echo    [3] Markdown 渲染器               (md-renderer)  Web: http://127.0.0.1:8082
echo.
echo  [0] 退出
echo.
set /p CH=请选择编号（0-3）：

if /i "%CH%"=="0" exit /b
if /i "%CH%"=="1" (call :launch "%BASE%\ai-chat\start_web.bat" & goto :menu)
if /i "%CH%"=="2" (call :launch "%BASE%\sandbox\start_web.bat" & goto :menu)
if /i "%CH%"=="3" (call :launch "%BASE%\md-renderer\start_web.bat" & goto :menu)

echo.
echo [!] 无效选择，请重新输入。
pause
goto :menu

:launch
if not exist "%~1" (
    echo.
    echo [~] 跳过（未找到启动脚本）：%~1
    goto :eof
)
start "" "%~1"
goto :eof
