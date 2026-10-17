@echo off
rem Headless compile of FTTest_straddle.mq5 with result verification.
rem Pattern from compile_multi_v2.bat: a back-to-back batch compile raced,
rem so this compiles ONE file and verifies the .ex5 timestamp actually moved.
set DST=C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\FTTest
set ME=C:\Program Files\MetaTrader 5\MetaEditor64.exe
set SRC=FTTest_straddle.mq5
set EX5=FTTest_straddle.ex5

for /f %%T in ('powershell -NoProfile -Command "if (Test-Path -Path '%DST%\%EX5%') { (Get-Item '%DST%\%EX5%').LastWriteTimeUtc.ToString('yyyyMMddHHmmss') } else { '0' }"') do set BEFORE=%%T
echo compiling %SRC% (ex5 before: %BEFORE%)
"%ME%" /compile:"%DST%\%SRC%" /log
ping -n 8 127.0.0.1 > nul
for /f %%T in ('powershell -NoProfile -Command "(Get-Item '%DST%\%EX5%').LastWriteTimeUtc.ToString('yyyyMMddHHmmss')"') do set AFTER=%%T
if "%AFTER%" GTR "%BEFORE%" (
  echo OK %EX5% updated -^> %AFTER%
) else (
  echo RETRY %SRC% ^(timestamp stale^)
  ping -n 16 127.0.0.1 > nul
  "%ME%" /compile:"%DST%\%SRC%" /log
  ping -n 8 127.0.0.1 > nul
  for /f %%T in ('powershell -NoProfile -Command "(Get-Item '%DST%\%EX5%').LastWriteTimeUtc.ToString('yyyyMMddHHmmss')"') do set AFTER2=%%T
  if "%AFTER2%" GTR "%BEFORE%" (echo OK on retry %EX5%) else (echo FAILED %SRC% - CHECK LOG)
)
echo ==== compile log result ====
powershell -NoProfile -Command "Get-Content '%DST%\FTTest_straddle.log' -Tail 8"
exit /b 0
