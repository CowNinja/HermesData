Set sh = CreateObject("WScript.Shell")
sh.Environment("Process")("HERMES_HOME") = "D:\HermesData"
sh.CurrentDirectory = "D:\HermesData"
' --replace recycles single gateway per SINGLE-GATEWAY-RESTORE
sh.Run "pythonw.exe -m hermes_cli.main gateway run --replace", 0, False
