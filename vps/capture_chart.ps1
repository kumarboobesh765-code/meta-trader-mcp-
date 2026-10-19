# Capture the console-session screen with the MT5 terminal foreground.
# Runs via a one-shot scheduled task (MTCapture) so it executes in the
# interactive session (an SSH context cannot capture the console desktop).
# Number of Ctrl+Tab chart-cycle presses is read from C:\FTTest\tabs.txt.
$tabs = 0
$tf = 'C:\FTTest\tabs.txt'
if (Test-Path $tf) { try { $tabs = [int](Get-Content $tf -First 1 -ErrorAction SilentlyContinue) } catch { $tabs = 0 } }

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class W2b {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
}
"@

[W]::SetProcessDPIAware() | Out-Null

$p = Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if ($p) {
  [W]::ShowWindow($p.MainWindowHandle, 3) | Out-Null   # SW_MAXIMIZE
  [W]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  Start-Sleep -Milliseconds 800
  $ws = New-Object -ComObject WScript.Shell
  if ($tabs -gt 0) {
    # Alt+W opens the Windows dialog (already proven reachable); arrow down
    # ($tabs-1) times from chart 1 to chart $tabs, then Enter to Activate.
    $ws.SendKeys('%w')
    Start-Sleep -Milliseconds 1500
    for ($i = 1; $i -lt $tabs; $i++) {
      $ws.SendKeys('{DOWN}')
      Start-Sleep -Milliseconds 350
    }
    Start-Sleep -Milliseconds 500
    $ws.SendKeys('{ENTER}')
    Start-Sleep -Milliseconds 2500
  }
}

# Save screenshot on the VPS, PNG.
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$out = 'C:\FTTest\screen.png'
$bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output ('saved ' + $out + ' tabs=' + $tabs + ' at ' + (Get-Date).ToString('HH:mm:ss') + ' term_pid=' + $(if($p){$p.Id}else{'none'}))
