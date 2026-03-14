@echo off
cd /d "C:\Jasweer\my_project\DiceAlerts"
python monitor.py --once >> monitor_output.log 2>&1
