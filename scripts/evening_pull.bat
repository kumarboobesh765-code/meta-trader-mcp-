@echo off
rem Evening dashboard pull -- run after the NY close (scheduled task
rem FTDashboardEvening). Fetches the VPS forward logs and rebuilds
rem charts/dashboard.html with the day's final results.
pushd "%~dp0.."
echo [%date% %time%] pulling VPS logs...
scp -i "%USERPROFILE%\.ssh\id_ed25519_vps" -o BatchMode=yes ^
  "Administrator@109.122.56.70:C:/FTTest/logs/forward/deals.csv" ^
  "Administrator@109.122.56.70:C:/FTTest/logs/forward/equity.csv" ^
  logs\forward\
if errorlevel 1 (
  echo [%date% %time%] PULL FAILED -- keeping previous dashboard
  popd
  exit /b 1
)
python scripts\forward_charts.py >> "%TEMP%\ft_dashboard_evening.log" 2>&1
echo [%date% %time%] dashboard regenerated (log: %%TEMP%%\ft_dashboard_evening.log)
popd
