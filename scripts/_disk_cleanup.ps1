# FTTest safe disk cleanup (run 2026-10-01; rerunnable)
# - archives MT5 journals + FTTest logs + tester reports older than 7 days
# - verifies the zip exists and is non-trivial before deleting anything
# - NEVER touches: deals.csv, the whole logs\forward\ dir, decisions.log,
#   state markers (*.marker *.sent *armed_ts retire_r2.*), scripts, MQL5 dirs
$ErrorActionPreference = "SilentlyContinue"
$stamp   = Get-Date -Format "yyyyMMdd_HHmm"
$zipPath = "C:\FTTest\archive\fttest_logs_$stamp.zip"
$cut     = (Get-Date).AddDays(-7)
New-Item -ItemType Directory -Force -Path "C:\FTTest\archive" | Out-Null

$freeBefore = [math]::Round((Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace/1GB, 2)

function Get-OldFiles($dir, $pattern) {
  if (-not (Test-Path $dir)) { return @() }
  Get-ChildItem -Path $dir -Filter $pattern -File |
    Where-Object { $_.LastWriteTime -lt $cut }
}

# ---- collect candidates -----------------------------------------------------
$targets = @()
$targets += Get-OldFiles "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\logs" "*.log"
# FTTest runtime logs: everything old EXCEPT protected names/patterns
$protect = @("decisions.log")
foreach ($f in (Get-OldFiles "C:\FTTest\logs" "*")) {
  if ($f.Name -in $protect) { continue }
  if ($f.Name -match "(\.marker$|\.sent$|armed_ts$|^retire_r2\.|deals\.csv$)") { continue }
  if ($f.FullName -like "*\forward\*") { continue }
  $targets += $f
}
$targets += Get-OldFiles "C:\FTTest\tester_reports" "*"

$totalBytes = ($targets | Measure-Object -Property Length -Sum).Sum
Write-Output ("candidates: {0} files, {1:N1} MB (older than {2:yyyy-MM-dd})" -f $targets.Count, ($totalBytes/1MB), $cut)
if ($targets.Count -eq 0) { Write-Output "nothing to archive -- done"; exit 0 }

# ---- archive ----------------------------------------------------------------
$paths = $targets | ForEach-Object { $_.FullName }
Compress-Archive -Path $paths -DestinationPath $zipPath -Update -CompressionLevel Optimal
if (-not (Test-Path $zipPath)) { Write-Output "ABORT: zip creation failed -- nothing deleted"; exit 1 }
$zipSize = (Get-Item $zipPath).Length
if ($zipSize -lt 1000) { Write-Output "ABORT: zip suspiciously small -- nothing deleted"; exit 1 }
Write-Output ("archived -> {0} ({1:N1} MB)" -f $zipPath, ($zipSize/1MB))

# ---- delete only what was archived ------------------------------------------
$deleted = 0; $freed = 0
foreach ($f in $targets) {
  Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
  if (-not (Test-Path -LiteralPath $f.FullName)) { $deleted++; $freed += $f.Length }
}
Write-Output ("deleted {0}/{1} files, freed {2:N1} MB" -f $deleted, $targets.Count, ($freed/1MB))

# ---- verify the protected records still exist -------------------------------
$mustExist = @(
  "C:\FTTest\logs\forward\deals.csv",
  "C:\FTTest\logs\decisions.log"
)
foreach ($p in $mustExist) {
  if (Test-Path $p) { Write-Output ("protected OK: {0} ({1:N0} KB)" -f $p, ((Get-Item $p).Length/1KB)) }
  else { Write-Output ("WARNING: protected file missing: {0}" -f $p) }
}

$freeAfter = [math]::Round((Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace/1GB, 2)
Write-Output ("disk C: free {0} GB -> {1} GB (+{2} GB)" -f $freeBefore, $freeAfter, [math]::Round($freeAfter-$freeBefore, 2))
