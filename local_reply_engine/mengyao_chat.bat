@echo off
title MengYao Local Engine
cd /d "%~dp0"
echo ============================================
echo   MengYao Local Engine
echo ============================================
echo   [1] Full      bge-m3        ~2.7GB RAM
echo   [2] Balanced  bge-small     ~160MB RAM
echo   [3] Lite      pure mock     ~32MB RAM
echo ============================================
set /p choice=Select 1/2/3 (Enter=1):
if "%choice%"=="2" set ARG=--balanced
if "%choice%"=="3" set ARG=--lite
if not defined ARG set ARG=--full
C:\Users\Dawn\.workbuddy\binaries\python\envs\default\Scripts\python.exe run_chat.py %ARG%
pause
