Option Explicit
Dim sh
Set sh = CreateObject("WScript.Shell")
sh.Run """C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe""" """D:\HermesData\scripts\silo_overnight_cook.py""" --hours 9 --sleep 12 --train-limit 40 --index-limit 40 --bb-limit 300 --ocr-limit 25", 0, False
