# Fresh-instance check: pid, start time, v1.01 init, all-EA init lines.
$ErrorActionPreference = "Continue"
Get-Process terminal64 | Select-Object Id, StartTime
$log = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Logs\20261015.log"
Write-Output "=== init lines (all EAs) ==="
Select-String -Path $log -Pattern "started on" | Select-Object -Last 6
Write-Output "=== REFUSING ==="
Select-String -Path $log -Pattern "REFUSING" | Select-Object -Last 3
