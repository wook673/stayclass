@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   영상메이커를 시작합니다... 잠시 후 브라우저가 자동으로 열립니다.
echo   (이 검은 창은 닫지 마세요. 닫으면 프로그램이 종료됩니다.)
echo.
python app.py
pause
