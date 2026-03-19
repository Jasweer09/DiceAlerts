@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8:replace
cd /d "C:\Jasweer\my_project\DiceAlerts"
python monitor.py --once >> monitor_output.log 2>&1
