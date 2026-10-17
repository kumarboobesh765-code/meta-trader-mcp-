@echo off
REM Run the trailing-SL window-slice probe once PER FAMILY.
REM A single all-in-one invocation stalled on one slow family; running each
REM separately means one slow family cannot block the rest of the verdict.
REM Output is appended so partial results survive a hang/timeout.
set LOG=C:\FTTest\logs\tw2.txt
del /q %LOG% 2>nul
for %%f in (breakout macross smc squeeze trend) do (
  echo ==== %%f ==== >> %LOG%
  C:\PROGRA~1\Python314\python.exe -u C:\FTTest\scripts\_trail_tighter_windows.py %%f >> %LOG% 2>&1
)
echo ALLDONE >> %LOG%