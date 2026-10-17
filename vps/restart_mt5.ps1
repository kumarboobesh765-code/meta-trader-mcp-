# Restart MT5 on the VPS: graceful close, wait, relaunch in console session.
$ErrorActionPreference = "Continue"
$p = Get-Process terminal64 -ErrorAction SilentlyContinue
if ($p) {
  Write-Output ("closing terminal64 pid=" + $p.Id)
  $p.CloseMainWindow() | Out-Null
  for ($i = 0; $i -lt 30 -and (Get-Process terminal64 -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Seconds 2 }
  if (Get-Process terminal64 -ErrorAction SilentlyContinue) {
    Write-Output "graceful close timed out; forcing"
    Stop-Process -Name terminal64 -Force
    Start-Sleep -Seconds 3
  }
} else {
  Write-Output "terminal64 not running"
}
Write-Output ("still running after close: " + [bool](Get-Process terminal64 -ErrorAction SilentlyContinue))
powershell -NoProfile -ExecutionPolicy Bypass -File C:\FTTest\mt_relaunch.ps1
Start-Sleep -Seconds 20
Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object Id, StartTime | Format-Table -AutoSize | Out-String
