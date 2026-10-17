@echo off
rem Kill only python processes running forward_test.py -- the start_fttest.bat
rem loop respawns the runner within 60s, picking up the freshly deployed code.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | Where-Object { $_.CommandLine -like '*forward_test.py*' } | ForEach-Object { Write-Output ('killing ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }"
echo kill done
