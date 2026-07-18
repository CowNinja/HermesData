@echo off
REM Hidden launcher — do NOT flash a console on the desktop.
REM Prefer pythonw so no conhost steals focus while Jeff types.
start "" /B "C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe" "D:\HermesData\scripts\silo_autonomous_watchdog.py" --stall-minutes 12 --hours 4 --sleep 40
exit /b 0
