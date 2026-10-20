# Click Window > Tile Vertically (entry at y=135 in the dropdown), then screenshot.
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class W5 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
}
"@
[W5]::SetProcessDPIAware() | Out-Null

$p = Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'no terminal64'; exit 1 }
[W5]::ShowWindow($p.MainWindowHandle, 3) | Out-Null   # SW_MAXIMIZE
[W5]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 900

function Click([int]$x, [int]$y) {
  [W5]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds 300
  [W5]::mouse_event([uint32]2, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 70
  [W5]::mouse_event([uint32]4, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 900
}

Click 277 33      # Window menu
Start-Sleep -Milliseconds 1100
Click 309 135     # Tile Vertically
Start-Sleep -Milliseconds 2200

Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save('C:\FTTest\screen.png', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output ('tiled vertically, captured ' + (Get-Date).ToString('HH:mm:ss'))
