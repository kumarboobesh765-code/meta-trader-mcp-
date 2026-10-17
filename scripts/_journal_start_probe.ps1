$dir = 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Logs'
Get-ChildItem "$dir\20261006.log", "$dir\20261007.log" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Output ("-- " + $_.Name + " --")
    $hits = Get-Content $_.FullName | Select-String 'started on'
    Write-Output ("   'started on' lines: " + ($hits | Measure-Object).Count)
    $hits | Select-Object -First 3 -Last 3 | ForEach-Object { Write-Output ("   " + $_.Line) }
}
