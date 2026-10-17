@echo off
rem Compile SlipstreamAltEA (alternating slipstream martingale, magic set on chart).
set DST=C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\FTTest
"C:\Program Files\MetaTrader 5\MetaEditor64.exe" /compile:"%DST%\SlipstreamAltEA.mq5" /log
ping -n 8 127.0.0.1 > nul
