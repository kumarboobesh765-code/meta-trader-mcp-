# Deep verify: any gridbestrr lines today, chart03 load errors, positions.
$ErrorActionPreference = "Continue"
$log = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Logs\20261015.log"
Write-Output "=== gridbestrr lines today ==="
Select-String -Path $log -Pattern "gridbestrr" | Select-Object -Last 10
Write-Output "=== expert load / fail lines ==="
Select-String -Path $log -Pattern "GridBestRR|930023|cannot load|expert.*failed|CExpert" | Select-Object -Last 10
