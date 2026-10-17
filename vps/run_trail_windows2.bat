@echo off
REM Trail window-slice probe, one family per invocation.
REM IMPORTANT: do NOT background these with `start` -- a detached python that
REM never reaches its first log line wedges silently and blocks the batch.
REM Each family is run in the FOREGROUND here so the next only starts after the
REM previous one has really finished.
REM Families already completed and appended to the log are skipped.
set LOG=C:\FTTest\logs\tw3.txt
del /q %LOG% 2>nul
for %%f in (smc squeeze trend) do (
  echo ==== %%f ==== >> %LOG%
  C:\PROGRA~1\Python314\python.exe -u C:\FTTest\scripts\_trail_tighter_windows.py %%f >> %LOG% 2>&1
)
echo ALLDONE >> %LOG%