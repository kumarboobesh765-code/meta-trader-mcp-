# One-shot probe on the VPS: find which FTTest profile chart hosts the
# straddle EA (magic 930004/940004), or confirm none does.
$dir = 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Profiles\Charts\FTTest'
Get-ChildItem "$dir\*.chr" | ForEach-Object {
    $hit = Select-String -Path $_.FullName -Pattern '930004|940004' | Select-Object -First 1
    if ($hit) {
        Write-Output ("$($_.Name) -> straddle magic present")
    }
}
Write-Output '--- charts and their EA/ex5 references ---'
Get-ChildItem "$dir\*.chr" | Where-Object { $_.Name -notlike '*.bak*' } | ForEach-Object {
    $ex5 = Select-String -Path $_.FullName -Pattern 'FTTest_straddle|FTTestEA' | Select-Object -First 1
    if ($ex5) {
        Write-Output ("$($_.Name) -> " + $ex5.Line.Trim())
    }
}
