Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\HermesData"
sh.Run "D:\HermesData\hermes-agent\venv\Scripts\pythonw.exe -m hermes_cli.main gateway run", 0, False
