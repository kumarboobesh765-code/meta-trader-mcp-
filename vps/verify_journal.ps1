# Journal progress: login, charts, experts, last lines with timestamps.
$ErrorActionPreference = "Continue"
$base = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
Write-Output "=== journal last 15 ==="
Get-Content "$base\Logs\20261015.log" | Select-Object -Last 15
Write-Output "=== MQL5 log last 3 ==="
Get-Content "$base\MQL5\Logs\20261015.log" | Select-Object -Last 3
