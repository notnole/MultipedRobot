@echo off
echo Starting Robot Commander Dashboard...
echo.
cd /d "%~dp0"

:: Try regular python first, then Anaconda locations
where python >nul 2>&1
if %errorlevel%==0 (
    set PYTHON=python
    goto :install
)

:: Check common Anaconda/Miniconda paths
for %%P in (
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "%LOCALAPPDATA%\anaconda3\python.exe"
    "%PROGRAMDATA%\anaconda3\python.exe"
    "C:\anaconda3\python.exe"
    "C:\ProgramData\Anaconda3\python.exe"
) do (
    if exist %%P (
        set PYTHON=%%~P
        goto :install
    )
)

echo ERROR: Python not found. Install Python or Anaconda and try again.
pause
exit /b 1

:install
echo Using: %PYTHON%
"%PYTHON%" -m pip install -q -r ..\requirements.txt
echo.
echo The browser will open automatically.
echo Press Ctrl+C in this window to stop the server.
echo.
"%PYTHON%" app.py
pause
