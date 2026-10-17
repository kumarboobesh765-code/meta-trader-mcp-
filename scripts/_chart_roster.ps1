$ErrorActionPreference = 'SilentlyContinue'
$dir = 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Profiles\Charts\FTTest'
Write-Output '=== CHART ROSTER (FTTest profile, active charts only) ==='
Get-ChildItem "$dir\*.chr" | Where-Object { $_.Name -notlike '*.bak*' } | Sort-Object { [int]($_.BaseName -replace '\D','') } | ForEach-Object {
    $t = Get-Content $_.FullName -Raw
    $name = ''
    if ($t -match 'name=([^\r\n]+)') { $name = $Matches[1] }
    $sym = ''
    if ($t -match 'symbol=([^\r\n]+)') { $sym = $Matches[1].Trim() }
    $period = ''
    if ($t -match 'period=(\d+)') { $period = $Matches[1] }
    $magic = ''
    if ($t -match 'il_InpMagic[=\s]*([\d]+)') { $magic = $Matches[1] }
    elseif ($t -match 'InpMagic[=\s]*([\d]+)') { $magic = $Matches[1] }
    Write-Output ($_.Name.PadRight(14) + ' ea=' + $name.PadRight(22) + ' sym=' + $sym.PadRight(8) + ' tf=' + $period.PadRight(6) + ' magic=' + $magic)
}
Write-Output ''
Write-Output '=== EA starts in today MQL5 journal ==='
$jr = Get-ChildItem 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Logs\*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($jr) {
    Write-Output ('journal: ' + $jr.Name)
    Get-Content $jr.FullName | Select-String 'started on|EA removed|REFUSING' | Select-Object -Last 30 | ForEach-Object { Write-Output $_.Line }
} else { Write-Output 'no journal found' }
