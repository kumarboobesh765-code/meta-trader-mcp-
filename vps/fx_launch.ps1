# Launch terminal64 with a tester /config in the interactive console session.
# Usage: powershell -File fx_launch.ps1 -Ini C:\FTTest\tester\fx_test.ini
param([string]$Ini = "C:\FTTest\fx_test.ini")
$mt5 = 'C:\PROGRA~1\METATR~1\TERMIN~1.EXE'
$st  = (Get-Date).AddMinutes(1).ToString('HH:mm')
schtasks /Create /TN FXTEST /TR "$mt5 /config:$Ini" /SC ONCE /ST $st /F | Out-Null
schtasks /Run /TN FXTEST
Start-Sleep -Seconds 5
schtasks /Delete /TN FXTEST /F | Out-Null
Write-Output ("FXTEST launched with " + $Ini + " at " + (Get-Date).ToString('HH:mm:ss'))
