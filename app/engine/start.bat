@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 若未创建虚拟环境则自动创建并安装依赖
if not exist ".venv" (
    echo 正在创建虚拟环境...
    py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [错误] 未找到 Python 运行时，也无法自动创建虚拟环境。
    echo   请先安装 Python 3.10+ 并勾选 "Add python.exe to PATH"，然后重试。
    pause
    exit /b 1
)

echo 正在检查依赖...
.venv\Scripts\python.exe -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo [警告] 依赖安装失败（可能是网络问题），尝试继续启动...
)

echo.
echo 启动 AI 对话命令行客户端...
echo 输入 /help 查看命令，/exit 退出。
echo.
.venv\Scripts\python.exe src/cli/chat.py %*
if errorlevel 1 (
    echo.
    echo [错误] 程序异常退出（错误码 %errorlevel%）。请查看上方信息。
)
pause
