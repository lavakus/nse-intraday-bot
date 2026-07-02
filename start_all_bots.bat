@echo off
:: Starts all trading bots (independent windows, survives Claude sessions).
cd /d C:\Users\ITS48\Desktop\TradingView
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONHOME=
set PYTHONPATH=
set PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
if not exist "%PY%" set PY=python

:: MT5 auto-trader (Gold + BTC)
start "MT5 Auto-Trader" /min cmd /k "cd /d C:\Users\ITS48\Desktop\TradingView & "%PY%" -u mt5_trader.py"
:: Main bot (NSE + Gold + BTC signals + Swing + Dashboard)
start "Main Bot" /min cmd /k "cd /d C:\Users\ITS48\Desktop\TradingView & "%PY%" run_all.py"
