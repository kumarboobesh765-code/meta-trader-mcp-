@echo off
rem Wrapper so Windows Task Scheduler can run the watchdog (Task: FTWatchdog).
bash "%~dp0vps_watchdog.sh" >> "%~dp0..\logs\watchdog.log" 2>&1
