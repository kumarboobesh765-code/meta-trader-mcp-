# Re-arm hourly 3-grid snapshots until tomorrow midday, then auto-expire.
# READ-ONLY probe; same script that produced the 14 clean snapshots.
$ErrorActionPreference = "Continue"
& schtasks /Delete /TN FTGridWatch2 /F 2>&1 | Out-Null
$ErrorActionPreference = "Stop"
schtasks /Create /TN FTGridWatch2 /TR "python C:\FTTest\scripts\_overnight_watch.py" /SC MINUTE /MO 60 /SD 10/15/2026 /ST 00:00 /ED 10/16/2026 /ET 12:00 /F
schtasks /Query /TN FTGridWatch2
