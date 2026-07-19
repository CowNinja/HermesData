Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
  public const uint MOUSEEVENTF_LEFTUP = 0x0004;
  public const int SW_RESTORE = 9;
  public const int SW_MAXIMIZE = 3;
}
[StructLayout(LayoutKind.Sequential)]
public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
[StructLayout(LayoutKind.Sequential)]
public struct POINT { public int X; public int Y; }
"@

$p = Get-Process -Name Trailmakers -ErrorAction Stop | Select-Object -First 1
$hwnd = $p.MainWindowHandle
Write-Output ("PID=" + $p.Id + " HWND=" + $hwnd)

[Win32]::ShowWindow($hwnd, 9) | Out-Null
Start-Sleep -Milliseconds 300
[Win32]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds 500

$fg = [Win32]::GetForegroundWindow()
Write-Output ("FOREGROUND_HWND=" + $fg + " MATCH=" + ($fg -eq $hwnd))

$client = New-Object RECT
[Win32]::GetClientRect($hwnd, [ref]$client) | Out-Null
$pt = New-Object POINT
$pt.X = 0; $pt.Y = 0
[Win32]::ClientToScreen($hwnd, [ref]$pt) | Out-Null
Write-Output ("CLIENT=" + $client.Right + "x" + $client.Bottom + " ORIGIN=" + $pt.X + "," + $pt.Y)

# Modal X is roughly 71% across, 18% down the client area (from captures)
$x = [int]($pt.X + $client.Right * 0.71)
$y = [int]($pt.Y + $client.Bottom * 0.18)
Write-Output ("CLICK_X=" + $x + " CLICK_Y=" + $y)

[Win32]::SetCursorPos($x, $y) | Out-Null
Start-Sleep -Milliseconds 200
[Win32]::mouse_event([Win32]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 50
[Win32]::mouse_event([Win32]::MOUSEEVENTF_LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 400

# Also send Escape as backup
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{ESC}")
Start-Sleep -Milliseconds 500
Write-Output "DONE_CLICK_AND_ESC"
