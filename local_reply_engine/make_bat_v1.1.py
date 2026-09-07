# -*- coding: utf-8 -*-
import os

content = (
    "@echo off\r\n"
    "title MengYao Local Engine\r\n"
    'cd /d "%~dp0"\r\n'
    "echo ============================================\r\n"
    "echo   MengYao Local Engine\r\n"
    "echo ============================================\r\n"
    "echo   [1] Full      bge-m3        ~2.7GB RAM\r\n"
    "echo   [2] Balanced  bge-small     ~160MB RAM\r\n"
    "echo   [3] Lite      pure mock     ~32MB RAM\r\n"
    "echo ============================================\r\n"
    "set /p choice=Select 1/2/3 (Enter=1):\r\n"
    'if "%choice%"=="2" set ARG=--balanced\r\n'
    'if "%choice%"=="3" set ARG=--lite\r\n'
    "if not defined ARG set ARG=--full\r\n"
    'C:\\Users\\Dawn\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe run_chat.py %ARG%\r\n'
    "pause\r\n"
)
for p in (
    r"C:\Users\Dawn\Desktop\local_reply_engine\mengyao_chat.bat",
    r"C:\Users\Dawn\Desktop\梦瑶引擎独立包\mengyao_chat.bat",
):
    with open(p, "w", encoding="ascii", newline="") as f:
        f.write(content)
    print("written:", p)
# 同步覆盖两个旧中文名 bat（内容相同，保留用户熟悉的名字）
for p in (
    r"C:\Users\Dawn\Desktop\local_reply_engine\梦瑶对话.bat",
    r"C:\Users\Dawn\Desktop\梦瑶引擎独立包\梦瑶对话.bat",
):
    with open(p, "w", encoding="ascii", newline="") as f:
        f.write(content)
    print("written:", p)
