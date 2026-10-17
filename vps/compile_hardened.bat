@echo off
rem Compile the two non-FTTest EAs hardened for trailing-SL behavior.
rem Same proven pattern as compile_newstrats.bat (timestamp verify + retry).
set DST=C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\FTTest
set ME=C:\Program Files\MetaTrader 5\MetaEditor64.exe
set FILES=XAUUSD_SmartMoney_VolumeProfile_EA.mq5 AetherFlowEA.mq5

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
