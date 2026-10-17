# One-shot MT5 relaunch in the interactive console session (SSH-safe).
# A plain `start` from an SSH session opens the GUI in the wrong session;
# a scheduled task run as the logged-on user lands in the console session.
# Short path (8.3) so schtasks /TR needs no inner quotes -- /TR quoting with
# spaces breaks under nested cmd/powershell shells.
$mt5 = 'C:\PROGRA~1\METATR~1\TERMIN~1.EXE'
$cfg = 'C:\FTTest\mt5_autologin.ini'
$st  = (Get-Date).AddMinutes(1).ToString('HH:mm')
schtasks /Create /TN MTRelaunch /TR "$mt5 /config:$cfg" /SC ONCE /ST $st /F | Out-Null
schtasks /Run /TN MTRelaunch
Start-Sleep -Seconds 8
Write-Output ("MTRelaunch fired at " + (Get-Date).ToString('HH:mm:ss') + " pid=" + (Get-Process terminal64 -ErrorAction SilentlyContinue).Id)
