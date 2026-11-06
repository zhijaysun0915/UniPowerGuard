@echo off
chcp 65001 >nul
title UniPowerGuard - Cross-Platform Power & Battery Manager
cd /d "%~dp0"
echo Starting UniPowerGuard on http://127.0.0.1:8095 ...
start "" "http://127.0.0.1:8095"
python server.py
pause
