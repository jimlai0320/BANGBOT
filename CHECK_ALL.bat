@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Run START.bat once first.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" run_checks.py
set "ERR=%errorlevel%"
pause
exit /b %ERR%
