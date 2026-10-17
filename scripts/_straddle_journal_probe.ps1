$dir = 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\FTTest'
Get-ChildItem "$dir\*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 5 | ForEach-Object {
    Write-Output ("LOG " + $_.Name + "  " + $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') + "  " + $_.Length)
}
# newest journal containing straddle activity
$newest = Get-ChildItem "$dir\*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($newest) {
    Write-Output ("--- tail of " + $newest.Name + " ---")
    Get-Content $newest.FullName -Tail 6
}
