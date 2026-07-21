Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\HermesData\scripts"
sh.Run """C:\Users\CowNi\AppData\Local\Programs\Python\Python311\pythonw.exe"" ""D:\HermesData\scripts\silo_continuous_loop.py"" --max-cycles 0", 0, False
