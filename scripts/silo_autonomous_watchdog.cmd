@echo off
REM Hidden launcher - do NOT flash a console on the desktop.
REM Prefer pythonw so no conhost steals focus while Jeff types.
REM 2026-07-21: --discord-alert posts board only when recovery fires.
start "" /B "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe" "D:\HermesData\scripts\silo_autonomous_watchdog.py" --stall-minutes 12 --hours 9 --sleep 30 --hb-stale-s 900 --discord-alert
exit /b 0