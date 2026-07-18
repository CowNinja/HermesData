Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\HermesData\scripts"
sh.Run "D:\HermesData\hermes-agent\venv\Scripts\python.exe D:\HermesData\scripts\sovereign_openai_proxy.py --host 127.0.0.1 --port 8091", 0, False
