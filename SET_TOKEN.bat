@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   Set Telegram Bot Token
echo ==========================================
set /p "BOT_TOKEN=Paste BotFather token: "
if "%BOT_TOKEN%"=="" (
    echo Token cannot be empty.
    pause
    exit /b 1
)
> ".env" echo BOT_TOKEN=%BOT_TOKEN%
echo.
echo Token saved to .env
echo You can now run START.bat
pause
