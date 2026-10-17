$ErrorActionPreference = "Continue"
Write-Output ("now=" + (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))
Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object Id, StartTime
$log = "C:\FTTest\logs\overnight_3grid_" + (Get-Date).ToString("yyyyMMdd") + ".txt"
if (Test-Path $log) { Write-Output "=== watch log tail ==="; Get-Content $log | Select-Object -Last 14 } else { Write-Output "no watch log yet: $log" }
$base = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
Write-Output "=== journal tail ==="
Get-ChildItem "$base\Logs" -Filter "*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { Write-Output ("file=" + $_.Name + " mtime=" + $_.LastWriteTime); Get-Content $_.FullName -Tail 4 }
Write-Output "=== EA logs (MQL5) tail ==="
Get-ChildItem "$base\MQL5\Logs" -Filter "*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { Write-Output ("file=" + $_.Name + " mtime=" + $_.LastWriteTime); Get-Content $_.FullName -Tail 8 }
