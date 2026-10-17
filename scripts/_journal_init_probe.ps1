$dir = 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Logs'
# Any line naming a FTTest EA + a magic number, or 'initialized' wording
Get-ChildItem "$dir\2026100*.log" | ForEach-Object {
    $hits = Get-Content $_.FullName | Select-String 'FTTest_\w+ \d{6,}|initialized|template.*applied|expert.*added'
    Write-Output ("-- " + $_.Name + "  hits=" + ($hits | Measure-Object).Count)
    $hits | Select-Object -First 4 | ForEach-Object { Write-Output ("   " + $_.Line) }
}
