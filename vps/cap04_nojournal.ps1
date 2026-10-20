# Maximize terminal, activate chart04, minimize the detached Journal window,
# capture, then restore the Journal window. Layout preserved.
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class W11 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
}
"@
[W11]::SetProcessDPIAware() | Out-Null
$p = Get-Process terminal64 -ErrorAction Stop | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
[W11]::ShowWindow($p.MainWindowHandle, 3) | Out-Null
[W11]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 900
$ws = New-Object -ComObject WScript.Shell
$ws.SendKeys('%w'); Start-Sleep -Milliseconds 1800
for ($i = 1; $i -lt 4; $i++) { $ws.SendKeys('{DOWN}'); Start-Sleep -Milliseconds 350 }
$ws.SendKeys('{ENTER}'); Start-Sleep -Milliseconds 2500
$ws.SendKeys('{ESC}'); Start-Sleep -Milliseconds 800

# enumerate terminal64 windows, minimize any titled Journal-ish window
$found = New-Object System.Collections.Generic.List[string]
$cb = [W11+EnumProc]{
  param($h, $l)
  $pid2 = 0
  [W11]::GetWindowThreadProcessId($h, [ref]$pid2) | Out-Null
  if ($pid2 -eq $p.Id -and [W11]::IsWindowVisible($h)) {
    $sb = New-Object System.Text.StringBuilder 256
    [W11]::GetWindowText($h, $sb, 256) | Out-Null
    $t = $sb.ToString()
    if ($t.Length -gt 0) { $found.Add(($h.ToString() + ' | ' + $t)) }
  }
  return $true
}
[W11]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
$found | ForEach-Object { Write-Output ('WIN ' + $_) }
$minimized = @()
foreach ($f in $found) {
  $hnd = [IntPtr]([long]($f.Split(' ')[0]))
  $title = $f.Substring($f.IndexOf('|') + 2)
  if ($title -match 'Journal' -and -not ($title -match 'XAUUSD')) {
    [W11]::ShowWindow($hnd, 6) | Out-Null   # SW_MINIMIZE
    $minimized += $hnd
    Write-Output ('minimized ' + $f)
  }
}
Start-Sleep -Milliseconds 1200

Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save('C:\FTTest\screen.png', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
foreach ($hnd in $minimized) { [W11]::ShowWindow($hnd, 9) | Out-Null }  # restore
Write-Output ('captured clean ' + (Get-Date).ToString('HH:mm:ss') + ' minimized=' + $minimized.Count)
