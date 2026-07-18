' Detached start for Phronesis-Gateway-Keepalive (survives parent shells / Grok jobs).
Option Explicit
Dim sh
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\HermesData\scripts"
sh.Run "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""D:\HermesData\scripts\Phronesis-Gateway-Keepalive.ps1"" -IntervalSec 60", 0, False
