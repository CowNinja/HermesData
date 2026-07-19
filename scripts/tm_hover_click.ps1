param(
  [double]$Fx = 0.06,
  [double]$Fy = 0.54,
  [int]$HoverMs = 400,
  [int]$Clicks = 1,
  [string]$ProcessName = "Trailmakers"
)

# True-foreground hover + click for Unity menus (AttachThreadInput + move trail + SendInput)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32h {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT lpPoint);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);
  [DllImport("user32.dll")] public static extern bool SetFocus(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);

  public const int INPUT_MOUSE = 0;
  public const uint MOUSEEVENTF_MOVE = 0x0001;
  public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
  public const uint MOUSEEVENTF_LEFTUP = 0x0004;
  public const uint MOUSEEVENTF_ABSOLUTE = 0x8000;

  [StructLayout(LayoutKind.Sequential)]
  public struct INPUT {
    public int type;
    public MOUSEINPUT mi;
  }
  [StructLayout(LayoutKind.Sequential)]
  public struct MOUSEINPUT {
    public int dx;
    public int dy;
    public uint mouseData;
    public uint dwFlags;
    public uint time;
    public IntPtr dwExtraInfo;
  }
}
[StructLayout(LayoutKind.Sequential)]
public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
[StructLayout(LayoutKind.Sequential)]
public struct POINT { public int X; public int Y; }
"@

Add-Type -AssemblyName System.Windows.Forms

function Send-AbsMouse([int]$x, [int]$y, [string]$action) {
  $sw = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width
  $sh = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height
  if ($sw -le 0) { $sw = 3600 }; if ($sh -le 0) { $sh = 1920 }
  $ax = [int][Math]::Round(65535.0 * $x / $sw)
  $ay = [int][Math]::Round(65535.0 * $y / $sh)
  $flags = switch ($action) {
    "move" { 0x8001 }  # ABSOLUTE|MOVE
    "down" { 0x8002 }  # ABSOLUTE|LEFTDOWN
    "up"   { 0x8004 }  # ABSOLUTE|LEFTUP
    default { 0x8001 }
  }
  $inp = New-Object 'Win32h+INPUT'
  $inp.type = 0
  $inp.mi = New-Object 'Win32h+MOUSEINPUT'
  $inp.mi.dx = $ax
  $inp.mi.dy = $ay
  $inp.mi.dwFlags = $flags
  $arr = @($inp)
  [void][Win32h]::SendInput(1, $arr, [Runtime.InteropServices.Marshal]::SizeOf([type]'Win32h+INPUT'))
}

$p = Get-Process -Name $ProcessName -ErrorAction Stop | Select-Object -First 1
$hwnd = $p.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero) { throw "No main window for $ProcessName" }

if ([Win32h]::IsIconic($hwnd)) { [void][Win32h]::ShowWindow($hwnd, 9) }
else { [void][Win32h]::ShowWindow($hwnd, 5) } # SW_SHOW

# AttachThreadInput so SetForegroundWindow sticks against UIPI focus rules
$fg = [Win32h]::GetForegroundWindow()
$fgPid = 0; $curPid = 0
$fgTid = [Win32h]::GetWindowThreadProcessId($fg, [ref]$fgPid)
$curTid = [Win32h]::GetCurrentThreadId()
$tgtTid = [Win32h]::GetWindowThreadProcessId($hwnd, [ref]$curPid)
$attached = $false
if ($fgTid -ne $tgtTid) {
  $attached = [Win32h]::AttachThreadInput($curTid, $fgTid, $true)
  [void][Win32h]::AttachThreadInput($curTid, $tgtTid, $true)
}
[void][Win32h]::BringWindowToTop($hwnd)
[void][Win32h]::SetForegroundWindow($hwnd)
[void][Win32h]::SetFocus($hwnd)
Start-Sleep -Milliseconds 200
if ($attached) {
  [void][Win32h]::AttachThreadInput($curTid, $fgTid, $false)
  [void][Win32h]::AttachThreadInput($curTid, $tgtTid, $false)
}

$client = New-Object RECT
[void][Win32h]::GetClientRect($hwnd, [ref]$client)
$origin = New-Object POINT
$origin.X = 0; $origin.Y = 0
[void][Win32h]::ClientToScreen($hwnd, [ref]$origin)

$tx = [int]($origin.X + $client.Right * $Fx)
$ty = [int]($origin.Y + $client.Bottom * $Fy)
$fgNow = [Win32h]::GetForegroundWindow()
Write-Output ("HWND=$hwnd FG_MATCH=$($fgNow -eq $hwnd) CLIENT=$($client.Right)x$($client.Bottom) ORIGIN=$($origin.X),$($origin.Y)")
Write-Output ("TARGET=$tx,$ty frac=$Fx,$Fy")

# Move trail (Unity often needs mouse-move over hitbox before click)
$steps = 8
$cur = New-Object POINT
[void][Win32h]::GetCursorPos([ref]$cur)
for ($s = 1; $s -le $steps; $s++) {
  $mx = [int]($cur.X + ($tx - $cur.X) * $s / $steps)
  $my = [int]($cur.Y + ($ty - $cur.Y) * $s / $steps)
  Send-AbsMouse $mx $my "move"
  Start-Sleep -Milliseconds 20
}
Send-AbsMouse $tx $ty "move"
[void][Win32h]::SetCursorPos($tx, $ty)
Start-Sleep -Milliseconds $HoverMs

for ($i = 0; $i -lt $Clicks; $i++) {
  Send-AbsMouse $tx $ty "down"
  Start-Sleep -Milliseconds 50
  Send-AbsMouse $tx $ty "up"
  Start-Sleep -Milliseconds 120
}
Write-Output "OK_HOVER_CLICK"
