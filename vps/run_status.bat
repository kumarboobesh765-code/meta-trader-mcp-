@echo off
echo ==== %date% %time% ==== > C:\FTTest\logs\status.txt
"C:\Program Files\Python314\python.exe" C:\FTTest\scripts\_status_check.py >> C:\FTTest\logs\status.txt 2>&1
echo EXITCODE=%ERRORLEVEL% >> C:\FTTest\logs\status.txt
