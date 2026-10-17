# Restart health: MQL5 log tail, terminal journal tail, any-EA lines.
$ErrorActionPreference = "Continue"
$base = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
Write-Output "=== MQL5 log last 5 ==="
Get-Content "$base\MQL5\Logs\20261015.log" | Select-Object -Last 5
Write-Output "=== journal last 12 ==="
Get-Content "$base\Logs\20261015.log" | Select-Object -Last 12
Write-Output "=== any EA prints after 10:20 ==="
Select-String -Path "$base\MQL5\Logs\20261015.log" -Pattern "gridrecovery|slipstream-clone|gridbestrr|REFUSING|started on" | Select-Object -Last 8
