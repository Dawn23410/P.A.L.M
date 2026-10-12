@echo off
chcp 936 >nul
title WebUI 启动
cd /d "%~dp0"

rem ============================================================
rem  WebUI 后台服务启动（启动后本窗口自动退出，服务常驻后台）
rem
rem  为什么不能双击 index.html：页面模块是 ES Module，浏览器出于 CORS
rem  限制不允许从 file:// 加载模块，必须经本地 http 服务。
rem
rem  本脚本做的事：找运行时 -> 起内核(10093) -> 起前端(5173)
rem                -> 等端口就绪 -> 打开浏览器 -> 立刻退出。
rem  服务是独立进程，本窗口关掉不影响它们。
rem
rem  可用参数：-NoBrowser  只起服务不开浏览器
rem ============================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\svc.ps1" -Action start %*

rem 成功则退出码 0，窗口直接关掉；失败才停住让你看清原因。
if errorlevel 1 (
  echo.
  echo   启动未成功，请查看上面的提示。按任意键关闭。
  pause >nul
)
exit /b
