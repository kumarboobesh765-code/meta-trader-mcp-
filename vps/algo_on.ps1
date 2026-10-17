# Toggle Algo Trading ON in the MT5 terminal (Ctrl+E hotkey) while the
# terminal sits in the interactive console session. Modeled on mt_relaunch.ps1:
# run via a scheduled task so keystrokes land in the user session (an SSH
# context cannot deliver keys reliably).
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
}
"@
$p = Get-Process terminal64 -ErrorAction Stop | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'no terminal window found'; exit 1 }
[W]::ShowWindow($p.MainWindowHandle, 9) | Out-Null   # SW_RESTORE
[W]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 800
$ws = New-Object -ComObject WScript.Shell
$ws.SendKeys('^e')                                   # Ctrl+E = toggle Algo Trading
Start-Sleep -Seconds 1
Write-Output ('Ctrl+E sent to pid ' + $p.Id + ' at ' + (Get-Date).ToString('HH:mm:ss'))
