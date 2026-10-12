@echo off
setlocal
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
> "logs\startup.log" echo [%date% %time%] BANG Dice Bot startup

echo ==========================================
echo   BANG Dice Telegram Bot - Local Windows
echo ==========================================

set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo [ERROR] Python was not found.
    echo Install Python 3.11 or newer, then run this file again.
    echo Python not found.>> "logs\startup.log"
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating virtual environment...
    %PY_CMD% -m venv .venv >> "logs\startup.log" 2>&1
    if errorlevel 1 (
        echo [ERROR] Could not create .venv.
        echo See logs\startup.log
        pause
        exit /b 1
    )

    echo [2/4] Installing packages...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >> "logs\startup.log" 2>&1
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt >> "logs\startup.log" 2>&1
    if errorlevel 1 (
        echo [ERROR] Package installation failed.
        echo See logs\startup.log
        pause
        exit /b 1
    )
) else (
    echo [1/4] Virtual environment OK.
    echo [2/4] Packages already installed.
)

if not exist ".env" (
    echo [ERROR] BOT_TOKEN is not configured.
    echo Run SET_TOKEN.bat first.
    pause
    exit /b 1
)

echo [3/4] Checking Python files...
".venv\Scripts\python.exe" -m py_compile bot.py game_engine.py ai.py renderer.py data.py old_saloon.py saloon_runtime.py saloon_bot.py saloon_dice_animation.py >> "logs\startup.log" 2>&1
if errorlevel 1 (
    echo [ERROR] Code check failed.
    echo See logs\startup.log
    pause
    exit /b 1
)

echo [4/4] Starting bot...
echo Keep this window open while the bot is running.
echo Runtime details are also saved to logs\bot.log
echo.
".venv\Scripts\python.exe" bot.py
set "ERR=%errorlevel%"

echo.
if not "%ERR%"=="0" (
    echo [ERROR] Bot stopped with exit code %ERR%.
    echo Please send logs\startup.log and logs\bot.log for diagnosis.
) else (
    echo Bot stopped normally.
)
pause
exit /b %ERR%
