@echo off
rem 24/7 loop for the Python forward test on the VPS. The runner NEVER
rem launches MetaTrader itself: if MT5 is closed it exits with a message and
rem this loop retries every 60s until MT5 is started (manually) and stays up.
rem Single-instance is enforced inside the runner (named mutex).
cd /d "%~dp0"
if not exist logs mkdir logs
set PY=C:\Program Files\Python314\python.exe
if not exist "%PY%" set PY=python
:loop
"%PY%" scripts\forward_test.py >> logs\forward_test_stdout.txt 2>&1
rem (ping sleep works in non-interactive sessions where `timeout` fails)
ping -n 61 127.0.0.1 >nul
goto loop
