param(
  [double]$Fx = 0.06,
  [double[]]$Fys = @(0.45,0.48,0.50,0.52,0.54,0.56,0.58,0.60,0.62)
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32g {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

  public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
  public const uint MOUSEEVENTF_LEFTUP = 0x0004;
  public const uint MOUSEEVENTF_MOVE = 0x0001;
  public const uint MOUSEEVENTF_ABSOLUTE = 0x8000;
  public const int INPUT_MOUSE = 0;

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
Add-Type -AssemblyName System.Drawing

function Click-Screen([int]$x, [int]$y) {
  $screenW = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width
  $screenH = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height
  $ax = [int](65535 * $x / $screenW)
  $ay = [int](65535 * $y / $screenH)
  $inputs = New-Object 'Win32g+INPUT[]' 3
  for ($i=0; $i -lt 3; $i++) {
    $inputs[$i] = New-Object 'Win32g+INPUT'
    $inputs[$i].type = 0
    $inputs[$i].mi = New-Object 'Win32g+MOUSEINPUT'
  }
  $inputs[0].mi.dx = $ax; $inputs[0].mi.dy = $ay
  $inputs[0].mi.dwFlags = 0x8001 # ABSOLUTE|MOVE
  $inputs[1].mi.dx = $ax; $inputs[1].mi.dy = $ay
  $inputs[1].mi.dwFlags = 0x8002 # ABSOLUTE|LEFTDOWN
  $inputs[2].mi.dx = $ax; $inputs[2].mi.dy = $ay
  $inputs[2].mi.dwFlags = 0x8004 # ABSOLUTE|LEFTUP
  [Win32g]::SendInput(3, $inputs, [System.Runtime.InteropServices.Marshal]::SizeOf([type]'Win32g+INPUT')) | Out-Null
}

$p = Get-Process -Name Trailmakers | Select-Object -First 1
$hwnd = $p.MainWindowHandle
[Win32g]::ShowWindow($hwnd, 9) | Out-Null
[Win32g]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds 300

$client = New-Object RECT
[Win32g]::GetClientRect($hwnd, [ref]$client) | Out-Null
$origin = New-Object POINT
$origin.X = 0; $origin.Y = 0
[Win32g]::ClientToScreen($hwnd, [ref]$origin) | Out-Null
Write-Output ("CLIENT=" + $client.Right + "x" + $client.Bottom + " ORIGIN=" + $origin.X + "," + $origin.Y)
Write-Output ("PRIMARY=" + [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width + "x" + [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height)

# Click only the FIRST fy in the list (caller loops)
$fy = $Fys[0]
$x = [int]($origin.X + $client.Right * $Fx)
$y = [int]($origin.Y + $client.Bottom * $fy)
Write-Output ("CLICK_SENDINPUT=" + $x + "," + $y + " frac=" + $Fx + "," + $fy)
Click-Screen $x $y
Start-Sleep -Milliseconds 600
Write-Output "OK"
