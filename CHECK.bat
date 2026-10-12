@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run START.bat once first.
    pause
    exit /b 1
)
echo Running game logic self-test...
".venv\Scripts\python.exe" selftest.py
echo.
pause
