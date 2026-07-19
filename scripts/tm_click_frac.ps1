param(
  [double]$Fx = 0.08,
  [double]$Fy = 0.28,
  [int]$Clicks = 1,
  [switch]$Right
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32c {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);
  public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
  public const uint MOUSEEVENTF_LEFTUP = 0x0004;
  public const uint MOUSEEVENTF_RIGHTDOWN = 0x0008;
  public const uint MOUSEEVENTF_RIGHTUP = 0x0010;
}
[StructLayout(LayoutKind.Sequential)]
public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
[StructLayout(LayoutKind.Sequential)]
public struct POINT { public int X; public int Y; }
"@

$p = Get-Process -Name Trailmakers -ErrorAction Stop |
  Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
  Select-Object -First 1
if (-not $p) { throw "No Trailmakers process with a main window" }
$hwnd = $p.MainWindowHandle
[Win32c]::ShowWindow($hwnd, 9) | Out-Null
[Win32c]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds 250

$client = New-Object RECT
[Win32c]::GetClientRect($hwnd, [ref]$client) | Out-Null
$pt = New-Object POINT
$pt.X = 0; $pt.Y = 0
[Win32c]::ClientToScreen($hwnd, [ref]$pt) | Out-Null

$x = [int]($pt.X + $client.Right * $Fx)
$y = [int]($pt.Y + $client.Bottom * $Fy)
Write-Output ("CLIENT=" + $client.Right + "x" + $client.Bottom + " CLICK=" + $x + "," + $y + " frac=" + $Fx + "," + $Fy)

for ($i = 0; $i -lt $Clicks; $i++) {
  [Win32c]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds 80
  if ($Right) {
    [Win32c]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 40
    [Win32c]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)
  } else {
    [Win32c]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 40
    [Win32c]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
  }
  Start-Sleep -Milliseconds 120
}
Write-Output "OK"
