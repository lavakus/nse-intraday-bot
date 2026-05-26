@echo off
title Trading Bot - NSE + GOLD + BTC [LIVE]
cd /d C:\Users\ITS48\Desktop\TradingView
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ============================================================
echo   UNIFIED TRADING BOT  ^|  NSE + GOLD + BTC
echo   Dashboard : http://localhost:5000
echo ============================================================
echo.

:loop
echo [%time%] Starting bot...
python run_all.py
echo.
echo [%time%] Bot stopped unexpectedly. Restarting in 10 seconds...
echo Press Ctrl+C to exit.
timeout /t 10 /nobreak
goto loop
