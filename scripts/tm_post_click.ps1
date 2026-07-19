param(
  [double]$Fx = 0.055,
  [double]$Fy = 0.61,
  [int]$Clicks = 1,
  [string]$ProcessName = "Trailmakers"
)

# Inject mouse click via PostMessage to game HWND (client coords) — bypasses OS cursor focus fights
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32p {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);

  public const uint WM_MOUSEMOVE = 0x0200;
  public const uint WM_LBUTTONDOWN = 0x0201;
  public const uint WM_LBUTTONUP = 0x0202;
  public const uint WM_LBUTTONDBLCLK = 0x0203;
  public const int MK_LBUTTON = 0x0001;

  public static IntPtr MakeLParam(int lo, int hi) {
    return (IntPtr)((hi << 16) | (lo & 0xFFFF));
  }
}
[StructLayout(LayoutKind.Sequential)]
public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
[StructLayout(LayoutKind.Sequential)]
public struct POINT { public int X; public int Y; }
"@

$p = Get-Process -Name $ProcessName -ErrorAction Stop |
  Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
  Select-Object -First 1
if (-not $p) { throw "No $ProcessName process with a main window" }
$hwnd = $p.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero) { throw "No main window" }

[void][Win32p]::ShowWindow($hwnd, 5)
[void][Win32p]::BringWindowToTop($hwnd)

# AttachThreadInput for true foreground
$fg = [Win32p]::GetForegroundWindow()
$dummy = [uint32]0
$fgTid = [Win32p]::GetWindowThreadProcessId($fg, [ref]$dummy)
$tgtTid = [Win32p]::GetWindowThreadProcessId($hwnd, [ref]$dummy)
$curTid = [Win32p]::GetCurrentThreadId()
if ($fgTid -ne $curTid) { [void][Win32p]::AttachThreadInput($curTid, $fgTid, $true) }
if ($tgtTid -ne $curTid) { [void][Win32p]::AttachThreadInput($curTid, $tgtTid, $true) }
[void][Win32p]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds 150

$client = New-Object RECT
[void][Win32p]::GetClientRect($hwnd, [ref]$client)
$cx = [int]($client.Right * $Fx)
$cy = [int]($client.Bottom * $Fy)
$lp = [Win32p]::MakeLParam($cx, $cy)

# Also move real cursor (some Unity builds need both)
$origin = New-Object POINT
$origin.X = 0; $origin.Y = 0
[void][Win32p]::ClientToScreen($hwnd, [ref]$origin)
$sx = $origin.X + $cx
$sy = $origin.Y + $cy
[void][Win32p]::SetCursorPos($sx, $sy)

Write-Output ("HWND=$hwnd CLIENT=$($client.Right)x$($client.Bottom) clientXY=$cx,$cy screen=$sx,$sy frac=$Fx,$Fy")
Write-Output ("FG_MATCH=$(([Win32p]::GetForegroundWindow()) -eq $hwnd)")

# Hover move via PostMessage
[void][Win32p]::PostMessage($hwnd, 0x0200, [IntPtr]::Zero, $lp) # WM_MOUSEMOVE
Start-Sleep -Milliseconds 350

for ($i = 0; $i -lt $Clicks; $i++) {
  # Real OS click
  [Win32p]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 40
  [Win32p]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
  # Posted messages as backup
  [void][Win32p]::PostMessage($hwnd, 0x0201, [IntPtr]1, $lp) # LBUTTONDOWN MK_LBUTTON
  Start-Sleep -Milliseconds 40
  [void][Win32p]::PostMessage($hwnd, 0x0202, [IntPtr]::Zero, $lp) # LBUTTONUP
  Start-Sleep -Milliseconds 150
}

if ($fgTid -ne $curTid) { [void][Win32p]::AttachThreadInput($curTid, $fgTid, $false) }
if ($tgtTid -ne $curTid) { [void][Win32p]::AttachThreadInput($curTid, $tgtTid, $false) }
Write-Output "OK_POST_CLICK"
