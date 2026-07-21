Option Explicit
Dim sh
Set sh = CreateObject("WScript.Shell")
sh.Run """C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"" ""D:\HermesData\scripts\launch_console_hidden.py"" -- ""C:\Users\CowNi\AppData\Local\Programs\Python\Python311\python.exe"" ""D:\HermesData\scripts\silo_autonomous_sprint.py"" --hours 9.0 --sleep 30 --smoke", 0, False
