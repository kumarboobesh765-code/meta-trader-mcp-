@echo off
rem Compile every LIVE FTTest EA source with the VPS MetaEditor headless compiler.
rem Covers: FTTest_<strategy>.mq5 (live families only; retired EAs archived to
rem C:\FTTest\retired_experts and removed from the Experts folder).
set DST=C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\FTTest
for %%f in ("%DST%\FTTest_*.mq5") do (
  "C:\Program Files\MetaTrader 5\MetaEditor64.exe" /compile:"%%f" /log
)
ping -n 8 127.0.0.1 > nul
echo ==== compile results ====
powershell -NoProfile -Command "Get-ChildItem '%DST%\*.log' | Where-Object { $_.Name -like 'FTTest*' } | ForEach-Object { $r = (Select-String -Path $_.FullName -Pattern 'Result:' | Select-Object -Last 1).Line; Write-Output ($_.Name + '  ' + $r) }"
