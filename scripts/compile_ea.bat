@echo off
rem Compile the FTTest EAs with MetaEditor's headless compiler (no GUI, no terminal).
rem Copies the sources from mql5\ first, then compiles in place.
rem Files: FTTestEA.mq5 + AetherFlowEA.mq5 (SMC Flow / UT Bot port, demo-only).
set DEST=%APPDATA%\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\FTTest
if not exist "%DEST%" mkdir "%DEST%"
set BASE=%~dp0..
copy /Y "%BASE%\mql5\FTTestEA.mq5" "%DEST%\" >nul
copy /Y "%BASE%\mql5\AetherFlowEA.mq5" "%DEST%\" >nul
powershell -NoProfile -Command "Start-Process -FilePath 'C:\Program Files\MetaTrader 5\MetaEditor64.exe' -ArgumentList '/compile:\"%DEST%\FTTestEA.mq5\"','/compile:\"%DEST%\AetherFlowEA.mq5\"','/log' -Wait | Out-Null"
echo Compile finished. Result lines:
powershell -NoProfile -Command "Get-Content '%DEST%\FTTestEA.log' | Select-Object -Last 1"
powershell -NoProfile -Command "Get-Content '%DEST%\AetherFlowEA.log' | Select-Object -Last 1"
exit /b %ERRORLEVEL%
