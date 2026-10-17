@echo off
rem Restart MetaTrader 5 after a wedge: kill the zombie terminal64, then
rem relaunch it. The FTTest profile (ProfileLast=FTTest) auto-loads with all
rem EA charts, and the start_fttest.bat loop reconnects the runner within 60s.
taskkill /F /IM terminal64.exe
ping -n 4 127.0.0.1 > nul
start "" "C:\Program Files\MetaTrader 5\terminal64.exe" /config:C:\FTTest\mt5_autologin.ini
echo MT5 relaunch issued at %time%
