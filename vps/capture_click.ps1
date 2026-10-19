# Click a point in the console-session screen, then screenshot.
# Runs via the MTCapture scheduled task (interactive session only).
# Coordinates are read from C:\FTTest\click.txt: "x y" (screen pixels).
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class W2 {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@

[W2]::SetProcessDPIAware() | Out-Null

$pt = (Get-Content 'C:\FTTest\click.txt' -First 1) -split '\s+'
$pts = @()
if ($pt.Count -ge 4) { $pts = @(@([int]$pt[0],[int]$pt[1]), @([int]$pt[2],[int]$pt[3])) }
else { $pts = @(@([int]$pt[0],[int]$pt[1])) }

foreach ($p in $pts) {
  [W2]::SetCursorPos($p[0], $p[1]) | Out-Null
  Start-Sleep -Milliseconds 250
  [W2]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)   # LEFTDOWN
  Start-Sleep -Milliseconds 60
  [W2]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)   # LEFTUP
  Start-Sleep -Milliseconds 800
}
Start-Sleep -Milliseconds 1500

Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save('C:\FTTest\screen.png', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
$xs = @(); foreach ($p in $pts) { $xs += -join ($p[0], ",", $p[1]) }
Write-Output ('clicked ' + ($xs -join ' -> ') + ' captured at ' + (Get-Date).ToString('HH:mm:ss'))
