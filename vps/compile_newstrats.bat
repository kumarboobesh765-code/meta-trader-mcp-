@echo off
rem Sequential single-file compiles with .ex5 timestamp verification each time.
rem The Core include changed -> every FTTest_* wrapper must recompile (the
rem include is inlined into each .ex5). Pattern from compile_multi_v2.bat.
set DST=C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\FTTest
set ME=C:\Program Files\MetaTrader 5\MetaEditor64.exe
set FILES=FTTest_trendpullback.mq5 FTTest_donchian.mq5 FTTest_trend.mq5 FTTest_supres.mq5 FTTest_supertrend.mq5 FTTest_liquiditysweep.mq5 FTTest_fixfade.mq5 FTTest_vwaprev.mq5 FTTest_breakout.mq5 FTTest_meanrev.mq5 FTTest_macross.mq5 FTTest_straddle.mq5 FTTest_smc.mq5 FTTest_london.mq5 FTTest_squeeze.mq5 FTTest_profile.mq5 FTTest_orderflow.mq5 FTTestEA.mq5 FTTest_dayopen.mq5 AetherFlowEA.mq5

for %%F in (%FILES%) do call :compile %%F
echo ==== DONE ALL ====
exit /b 0

:compile
set SRC=%~1
set EX5=%SRC:.mq5=.ex5%
set NEWER=0
for /f %%T in ('powershell -NoProfile -Command "if (Test-Path -Path '%DST%\%EX5%') { (Get-Item '%DST%\%EX5%').LastWriteTimeUtc.ToString('yyyyMMddHHmmss') } else { '0' }"') do set BEFORE=%%T
echo compiling %SRC% (ex5 before: %BEFORE%)
"%ME%" /compile:"%DST%\%SRC%" /log
ping -n 8 127.0.0.1 > nul
for /f %%T in ('powershell -NoProfile -Command "(Get-Item '%DST%\%EX5%').LastWriteTimeUtc.ToString('yyyyMMddHHmmss')"') do set AFTER=%%T
if "%AFTER%" GTR "%BEFORE%" (
  echo   OK %EX5% updated -^> %AFTER%
) else (
  echo   RETRY %SRC% ^(timestamp stale^)
  ping -n 16 127.0.0.1 > nul
  "%ME%" /compile:"%DST%\%SRC%" /log
  ping -n 8 127.0.0.1 > nul
  for /f %%T in ('powershell -NoProfile -Command "(Get-Item '%DST%\%EX5%').LastWriteTimeUtc.ToString('yyyyMMddHHmmss')"') do set AFTER2=%%T
  if "%AFTER2%" GTR "%BEFORE%" (echo   OK on retry %EX5%) else (echo   FAILED %SRC% - CHECK LOG)
)
powershell -NoProfile -Command "Get-Content '%DST%\%SRC:.mq5=.log%' | Select-String -Pattern 'error' | Select-Object -First 3"
exit /b 0
