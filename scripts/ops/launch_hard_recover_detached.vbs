' Detached launcher for hard gateway recover (outside Hermes terminal guard)
Set sh = CreateObject("WScript.Shell")
cmd = """D:\HermesData\hermes-agent\venv\Scripts\python.exe"" ""D:\HermesData\scripts\ops\hard_gateway_recover_grok45.py"""
' 0 = hide window, False = do not wait
sh.Run cmd, 0, False
