@echo off
rem Compile GridRecoveryEA (930021) after its source defaults change (LotMult 1.5, MaxLayers 4).
set DST=C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\FTTest
"C:\Program Files\MetaTrader 5\MetaEditor64.exe" /compile:"%DST%\GridRecoveryEA.mq5" /log
ping -n 8 127.0.0.1 > nul
powershell -NoProfile -Command "Select-String -Path '%DST%\GridRecoveryEA.log' -Pattern 'Result:' | Select-Object -Last 1 | ForEach-Object { $_.Line }"
