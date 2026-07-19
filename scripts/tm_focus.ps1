param(
  [string]$ProcessName = "Trailmakers"
)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32f {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
  [DllImport("user32.dll")] public static extern bool AllowSetForegroundWindow(int dwProcessId);
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
  public static readonly IntPtr HWND_NOTOPMOST = new IntPtr(-2);
  public const uint SWP_NOMOVE = 0x0002;
  public const uint SWP_NOSIZE = 0x0001;
  public const uint SWP_SHOWWINDOW = 0x0040;
}
"@
$p = Get-Process -Name $ProcessName -ErrorAction Stop |
  Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
  Select-Object -First 1
if (-not $p) { throw "No $ProcessName process with a main window" }
$hwnd = $p.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero) { throw "No main window" }

# Allow us to set FG
[void][Win32f]::AllowSetForegroundWindow(-1) # ASFW_ANY
if ([Win32f]::IsIconic($hwnd)) { [void][Win32f]::ShowWindow($hwnd, 9) } # SW_RESTORE
else { [void][Win32f]::ShowWindow($hwnd, 5) } # SW_SHOW

$fg = [Win32f]::GetForegroundWindow()
$dummy = [uint32]0
$fgTid = [Win32f]::GetWindowThreadProcessId($fg, [ref]$dummy)
$tgtTid = [Win32f]::GetWindowThreadProcessId($hwnd, [ref]$dummy)
$curTid = [Win32f]::GetCurrentThreadId()
if ($fgTid -ne $curTid) { [void][Win32f]::AttachThreadInput($curTid, $fgTid, $true) }
if ($tgtTid -ne $curTid) { [void][Win32f]::AttachThreadInput($curTid, $tgtTid, $true) }

# Alt key trick to unlock SetForegroundWindow restrictions
[Win32f]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero) # ALT down
[Win32f]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero) # ALT up

[void][Win32f]::BringWindowToTop($hwnd)
[void][Win32f]::SetWindowPos($hwnd, [Win32f]::HWND_TOPMOST, 0, 0, 0, 0, 0x0003 -bor 0x0040)
[void][Win32f]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds 80
[void][Win32f]::SetWindowPos($hwnd, [Win32f]::HWND_NOTOPMOST, 0, 0, 0, 0, 0x0003 -bor 0x0040)
[void][Win32f]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds 120

if ($fgTid -ne $curTid) { [void][Win32f]::AttachThreadInput($curTid, $fgTid, $false) }
if ($tgtTid -ne $curTid) { [void][Win32f]::AttachThreadInput($curTid, $tgtTid, $false) }

$now = [Win32f]::GetForegroundWindow()
Write-Output ("PID={0} HWND={1} FG={2} MATCH={3}" -f $p.Id, $hwnd, $now, ($now -eq $hwnd))
