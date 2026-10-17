param(
  [string]$Dir = "mql5"
)
try {
  $a = Get-ChildItem -Path $Dir -ErrorAction SilentlyContinue
  if ($null -ne $a) {
    if ($a.Count -gt 0) { Write-Output ("$Dir exists, items: " + $a.Count) }
    else { Write-Output ("$Dir exists, empty") }
  } else {
    Write-Output ("$Dir NO")
  }
} catch {
  Write-Output ("$Dir error: " + $_.Exception.Message)
}

Write-Output "---"
try {
  $b = Get-ChildItem -Path "scripts" -ErrorAction SilentlyContinue
  if ($null -ne $b) {
    if ($b.Count -gt 0) { Write-Output ("scripts exists, items: " + $b.Count) }
    else { Write-Output "scripts empty" }
  } else { Write-Output "scripts NO" }
} catch { Write-Output "scripts error: " + $_.Exception.Message }

Write-Output "---"
try {
  $c = Get-ChildItem -Path "logs" -ErrorAction SilentlyContinue
  if ($null -ne $c) {
    if ($c.Count -gt 0) { Write-Output ("logs exists, items: " + $c.Count) }
    else { Write-Output "logs empty" }
  } else { Write-Output "logs NO" }
} catch { Write-Output "logs error: " + $_.Exception.Message }
