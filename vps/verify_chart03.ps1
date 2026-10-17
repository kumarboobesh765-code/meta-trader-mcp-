# Chart03 file integrity: exists, size, input lines raw.
$ErrorActionPreference = "Continue"
$d = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Profiles\Charts\FTTest"
Write-Output "=== chart files ==="
Get-ChildItem $d | Select-Object Name, Length, LastWriteTime
$f = Join-Path $d "chart03.chr"
Write-Output "=== chart03 exists ==="
Test-Path $f
if (Test-Path $f) {
  $t = [System.IO.File]::ReadAllText($f)
  Write-Output ("LEN=" + $t.Length)
  $i = $t.IndexOf("InpMagic")
  if ($i -ge 0) { Write-Output $t.Substring([Math]::Max(0, $i - 600), [Math]::Min(900, $t.Length - [Math]::Max(0, $i - 600))) }
  else { Write-Output "NO_InpMagic_FOUND"; Write-Output $t.Substring(0, [Math]::Min(500, $t.Length)) }
}
