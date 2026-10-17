# Verify v1.01 rollout: terminal alive, init line, positions intact.
$ErrorActionPreference = "Continue"
$p = Get-Process terminal64 -ErrorAction SilentlyContinue
if ($p) { Write-Output ("TERMINAL_ALIVE pid=" + $p.Id) } else { Write-Output "TERMINAL_DEAD" }
$log = Get-ChildItem "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\*\MQL5\Logs\20261015.log" | Select-Object -First 1 -ExpandProperty FullName
Write-Output ("LOG=" + $log)
Select-String -Path $log -Pattern "gridbestrr 930023 v1.01" | Select-Object -Last 3
Select-String -Path $log -Pattern "REFUSING" | Select-Object -Last 5
