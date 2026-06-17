@echo off
cd /d C:\Users\ITS48\Desktop\TradingView
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONHOME=
set PYTHONPATH=
set PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
if not exist "%PY%" set PY=python
"%PY%" daily_report.py
