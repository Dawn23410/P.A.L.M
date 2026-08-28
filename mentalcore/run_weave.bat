@echo off
cd /d "%~dp0"
setlocal
rem 织语层（WeaveFace）独立服务 —— 从心智魔方核心拆出，默认本地 Mock 模式。
rem 无窗口常驻由 P.A.L.M一键启动.bat 负责拉起本脚本。
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
rem 织语层默认本地 Mock：不依赖 MockLLM / 存储 / Chroma，仅需 WeaveFace + 角色卡。
rem 设 WEAVE_MODE=bridge 可转发到心智魔方桥接（默认 7788）走完整六面流水线。
if not defined WEAVE_MODE set "WEAVE_MODE=mock"
if not defined WEAVE_PORT set "WEAVE_PORT=7799"
"%PY%" "%~dp0weave_layer.py"
endlocal
