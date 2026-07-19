param(
  [string]$Keys = ""
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32k {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
  public const uint KEYEVENTF_KEYUP = 0x0002;
}
"@
Add-Type -AssemblyName System.Windows.Forms

$p = Get-Process -Name Trailmakers -ErrorAction Stop |
  Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
  Select-Object -First 1
if (-not $p) { throw "No Trailmakers process with a main window" }
$hwnd = $p.MainWindowHandle
[Win32k]::ShowWindow($hwnd, 9) | Out-Null
[Win32k]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds 400

if ($Keys -ne "") {
  [System.Windows.Forms.SendKeys]::SendWait($Keys)
  Write-Output ("SENT=" + $Keys)
} else {
  Write-Output "NO_KEYS"
}
