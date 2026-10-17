@echo off
taskkill /F /FI "SESSION eq 0" /IM python.exe >nul 2>&1
"C:\Program Files\Python314\python.exe" -u C:\FTTest\scripts\_probe_init.py > C:\FTTest\logs\probe.txt 2>&1
