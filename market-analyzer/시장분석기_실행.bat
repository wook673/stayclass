@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 시장분석기 서버를 시작합니다... (창을 닫으면 서버가 종료됩니다)
start "" http://localhost:8899
set PYTHONIOENCODING=utf-8
python web.py
pause
