# Read-only recon of the VPS MT5 data folder: <expert> block format, chart
# period encoding, terminal64.ini (profile auto-load + algo-trading keys).
$root = 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075'

Write-Host '=== EXPERT BLOCK (Default\chart02.chr) ==='
$chart = Join-Path $root 'MQL5\Profiles\Charts\Default\chart02.chr'
Select-String -Path $chart -Pattern '<expert>' -Context 0,45 | ForEach-Object {
    Write-Host $_.Line
    $_.Context.PostContext | ForEach-Object { Write-Host $_ }
}

Write-Host '=== CHART PERIOD ENCODING (all .chr) ==='
Get-ChildItem (Join-Path $root 'MQL5\Profiles\Charts') -Recurse -Filter *.chr |
  ForEach-Object {
      $s = (Select-String -Path $_.FullName `
              -Pattern '^(symbol|period_type|period_size|digits|tick_size|windows_total)=' |
            ForEach-Object Line) -join ' | '
      Write-Host ($_.Directory.Name + '\' + $_.Name + ' :: ' + $s)
  }

Write-Host '=== INI FILES ==='
Get-ChildItem $root -Filter *.ini -Recurse -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host $_.FullName }
foreach ($p in @("$root\terminal64.ini", "$root\config\terminal64.ini", "$root\config\common.ini")) {
    if (Test-Path $p) {
        Write-Host "=== $p ==="
        Get-Content $p
    }
}
Write-Host '=== DONE ==='
