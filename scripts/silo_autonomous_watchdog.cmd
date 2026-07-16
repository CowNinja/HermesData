@echo off
REM Hermes silo autonomous flake watchdog — zero Grok
"C:\Program Files\Python313\python.exe" "D:\HermesData\scripts\silo_autonomous_watchdog.py" --stall-minutes 12 --hours 4 --sleep 40
