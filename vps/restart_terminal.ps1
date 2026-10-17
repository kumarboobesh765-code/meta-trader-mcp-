# Clean restart: stop terminal64, wait for exit, confirm dead.
$ErrorActionPreference = "Continue"
$p = Get-Process terminal64 -ErrorAction SilentlyContinue
if ($p) {
  Write-Output ("STOPPING pid=" + $p.Id)
  Stop-Process -Force -InputObject $p
  Start-Sleep 10
}
$p2 = Get-Process terminal64 -ErrorAction SilentlyContinue
if ($p2) { Write-Output ("STILL_ALIVE pid=" + $p2.Id) }
else { Write-Output "TERMINAL_STOPPED" }
