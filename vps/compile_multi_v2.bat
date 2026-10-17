@echo off
rem Single-file compile with result verification (the batch compile raced:
rem back-to-back MetaEditor launches share one instance and some compiles
rem were silently dropped while a STALE log still said "0 errors").
set DST=C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\FTTest
set ME="C:\Program Files\MetaTrader 5\MetaEditor64.exe"
%ME% /compile:"%DST%\FTTestMultiEA.mq5" /log
ping -n 6 127.0.0.1 > nul
echo ==== result ====
powershell -NoProfile -Command "Get-Item '%DST%\FTTestMultiEA.ex5' | Select-Object Length,LastWriteTime | Format-Table -AutoSize"
type "%DST%\FTTestMultiEA.log"
