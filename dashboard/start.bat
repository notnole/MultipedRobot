@echo off
echo Starting Robot Commander Dashboard...
echo.
echo The browser will open automatically.
echo Press Ctrl+C in this window to stop the server.
echo.
cd /d "%~dp0"
python app.py
pause
