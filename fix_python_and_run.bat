@echo off
title Fix Python + Start Trading Bot
cd /d C:\Users\ITS48\Desktop\TradingView
color 0A

echo ============================================================
echo   PYTHON FIX + TRADING BOT LAUNCHER
echo ============================================================
echo.

:: ── Check if Python works ────────────────────────────────────
python -c "import os" 2>nul
if %errorlevel% neq 0 (
    echo [!] Python standard library is MISSING or BROKEN.
    echo [!] Will download and install Python 3.11 now...
    echo.
    goto install_python
)
echo [OK] Python is working.
goto run_bots

:install_python
echo Downloading Python 3.11.9 installer...
powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%TEMP%\python_installer.exe' -UseBasicParsing"
if %errorlevel% neq 0 (
    echo [ERROR] Download failed. Check your internet connection.
    echo Please manually download Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installing Python 3.11.9...
"%TEMP%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
if %errorlevel% neq 0 (
    echo [ERROR] Installation failed. Running interactive installer...
    "%TEMP%\python_installer.exe"
)

:: Refresh PATH
call refreshenv 2>nul
set "PATH=%LOCALAPPDATA%\Programs\Python\Python311\;%LOCALAPPDATA%\Programs\Python\Python311\Scripts\;%PATH%"

echo.
echo [OK] Python 3.11 installed!
echo.

:: Install dependencies
echo Installing required packages...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo [OK] Packages installed!
echo.

:run_bots
:: ── Verify all imports work ────────────────────────────────
echo Checking bot dependencies...
python -c "import flask, yfinance, pandas, numpy, requests; print('[OK] All packages found')"
if %errorlevel% neq 0 (
    echo [!] Some packages missing. Installing...
    python -m pip install -r requirements.txt
)

echo.
echo ============================================================
echo   STARTING ALL BOTS
echo   NSE + GOLD + BTC + Dashboard + Swing Scanner
echo ============================================================
echo.

:: ── Start swing scanner in a separate window ─────────────
echo Starting today's Swing Scan in background...
start "Swing Scanner" cmd /k "cd /d C:\Users\ITS48\Desktop\TradingView && python run_swing.py && echo Swing scan complete. && pause"

:: Wait a moment before starting main bot
timeout /t 3 /nobreak > nul

:: ── Start main bot (NSE + GOLD + BTC + Dashboard) ────────
echo Starting main bot (NSE + GOLD + BTC + Dashboard)...
echo Dashboard will be at: http://localhost:5000
echo.

:loop
python run_all.py
echo.
echo [%time%] Bot stopped. Restarting in 10 seconds...
echo Press Ctrl+C to stop.
timeout /t 10 /nobreak
goto loop
