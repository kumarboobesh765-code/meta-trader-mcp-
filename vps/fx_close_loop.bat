@echo off
rem Detached FX-cleanup loop: the closer is idempotent (cancels non-XAU
rem pendings first, then closes non-XAU positions, XAU untouched). It exits 0
rem when the account has no non-XAU exposure left. One order_send can wedge
rem on the 1 GB box, so we loop with a fresh process each round instead of
rem retrying inside a possibly-dead IPC session.
set PY=C:\PROGRA~1\Python314\python.exe
set LOG=C:\FTTest\logs\fx_close_rounds.log
set /a ROUND=0
:loop
set /a ROUND+=1
echo ==== round %ROUND% %date% %time% ==== >> "%LOG%"
"%PY%" C:\FTTest\scripts\_close_fx_once.py >> "%LOG%" 2>&1
if errorlevel 1 goto next
goto done
:next
if %ROUND% GEQ 40 goto giveup
ping -n 11 127.0.0.1 > nul
goto loop
:done
echo ==== CLEAN after %ROUND% rounds ==== >> "%LOG%"
exit /b 0
:giveup
echo ==== GAVE UP after %ROUND% rounds, manual attention needed ==== >> "%LOG%"
exit /b 1
