# Ensure terminal maximized, chart04 active via Alt+W dialog, Esc to dismiss
# Journal popups, then screenshot.
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class W8 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
[W8]::SetProcessDPIAware() | Out-Null
$p = Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'no terminal'; exit 1 }
[W8]::ShowWindow($p.MainWindowHandle, 3) | Out-Null
[W8]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 900
$ws = New-Object -ComObject WScript.Shell
$ws.SendKeys('%w')
Start-Sleep -Milliseconds 1800
for ($i = 1; $i -lt 4; $i++) { $ws.SendKeys('{DOWN}'); Start-Sleep -Milliseconds 350 }
Start-Sleep -Milliseconds 500
$ws.SendKeys('{ENTER}')
Start-Sleep -Milliseconds 2500
$ws.SendKeys('{ESC}')                                 # dismiss any Journal popup
Start-Sleep -Milliseconds 1200
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save('C:\FTTest\screen.png', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output ('captured clean ' + (Get-Date).ToString('HH:mm:ss'))
