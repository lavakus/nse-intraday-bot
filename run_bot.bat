@echo off
title Trading Bot - NSE + GOLD + BTC [LIVE]
cd /d C:\Users\ITS48\Desktop\TradingView
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONHOME=
set PYTHONPATH=

:: ── Use Python 3.11 (stable, full stdlib) ────────────────
set PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
if not exist "%PY%" set PY=python

echo ============================================================
echo   UNIFIED TRADING BOT  ^|  NSE + GOLD + BTC
echo   Dashboard : http://localhost:5000
echo   Python    : %PY%
echo ============================================================
echo.

:: Quick health check
"%PY%" -c "import os, sys, flask, yfinance, pandas" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python or packages broken. Run fix_python_and_run.bat first.
    pause
    exit /b 1
)
echo [OK] Python 3.11 + all packages verified
echo.

:: ── Start today's Swing Scan in a separate window ────────
echo Starting Swing Scan window...
start "Swing Scanner [%date%]" cmd /k "set PYTHONHOME=&set PYTHONPATH=&cd /d C:\Users\ITS48\Desktop\TradingView & %PY% run_swing.py & echo. & echo Swing scan done. Press any key to close. & pause"

timeout /t 2 /nobreak > nul

:: ── Start MT5 Auto-Trader (Gold + BTC via XM) in its own window ──
:: NOTE: MetaTrader 5 must be OPEN and LOGGED IN to your XM demo account,
::       with "Algo Trading" enabled, before this can place trades.
echo Starting MT5 Auto-Trader window...
start "MT5 Auto-Trader [%date%]" cmd /k "set PYTHONHOME=&set PYTHONPATH=&cd /d C:\Users\ITS48\Desktop\TradingView & %PY% mt5_trader.py & echo. & echo MT5 trader stopped. Press any key to close. & pause"

timeout /t 2 /nobreak > nul

:: ── Main bot loop (NSE + GOLD + BTC + Dashboard) ─────────
:loop
echo [%time%] Starting main bot...
"%PY%" run_all.py
echo.
echo [%time%] Bot stopped. Restarting in 10 seconds... (Ctrl+C to exit)
timeout /t 10 /nobreak
goto loop
