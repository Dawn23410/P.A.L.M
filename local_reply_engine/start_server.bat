@echo off
title PALM Models API - Mengyao Local Engine
cd /d "%~dp0"
echo ============================================
echo   PALM Models API  /p.a.l.m/models/api
echo   Tier ports: full=10000 balanced=10001
echo               lite=10002
echo ============================================
echo   [1] Full      bge-m3     port 10000
echo   [2] Balanced  bge-small  port 10001
echo   [3] Lite      mock       port 10002
echo ============================================
set /p choice=Select 1/2/3 (Enter=1):
if "%choice%"=="2" set TIER=--tier balanced
if "%choice%"=="3" set TIER=--tier lite
if not defined TIER set TIER=--tier full
"C:\Users\Dawn\.workbuddy\binaries\python\envs\default\Scripts\python.exe" start_server.py %TIER% --preload
pause
