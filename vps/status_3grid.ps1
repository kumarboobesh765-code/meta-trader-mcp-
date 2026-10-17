# Status: terminal alive, EA lines since v1.01 start, journal tail.
$ErrorActionPreference = "Continue"
Get-Process terminal64 | Select-Object Id, StartTime
$base = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
Write-Output "=== gridbestrr since 10:34 ==="
Select-String -Path "$base\MQL5\Logs\20261015.log" -Pattern "gridbestrr" | Where-Object { $_.Line -match "10:3[4-9]|10:4[0-9]|1[1-9]:" } | Select-Object -Last 12
Write-Output "=== other EAs last 4 ==="
Select-String -Path "$base\MQL5\Logs\20261015.log" -Pattern "gridrecovery (basket|new cycle|layer)|slipstream-clone basket" | Select-Object -Last 4
Write-Output "=== journal last 3 ==="
Get-Content "$base\Logs\20261015.log" | Select-Object -Last 3
