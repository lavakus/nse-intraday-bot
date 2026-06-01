@echo off
title Trading Bot - NSE + GOLD + BTC [LIVE]
cd /d C:\Users\ITS48\Desktop\TradingView
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
:: Clear broken PYTHONHOME/PYTHONPATH that can corrupt the Python runtime
set PYTHONHOME=
set PYTHONPATH=

echo ============================================================
echo   UNIFIED TRADING BOT  ^|  NSE + GOLD + BTC
echo   Dashboard : http://localhost:5000
echo ============================================================
echo.

:: ── Quick Python health check ─────────────────────────────
python -c "import os, sys" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python standard library is missing/broken!
    echo.
    echo Please fix Python first:
    echo   1. Run fix_python_and_run.bat  (auto-fix)
    echo   OR
    echo   2. Download Python 3.11 from https://www.python.org/downloads/
    echo      Install it, then run this bat again.
    echo.
    pause
    exit /b 1
)

echo [OK] Python OK — starting bots...
echo.

:loop
echo [%time%] Starting bot...
python run_all.py
echo.
echo [%time%] Bot stopped unexpectedly. Restarting in 10 seconds...
echo Press Ctrl+C to exit.
timeout /t 10 /nobreak
goto loop
