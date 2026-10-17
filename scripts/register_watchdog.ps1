# Register the FTWatchdog task: runs scripts/vps_watchdog.bat every 30 minutes
# to pull VPS trade logs and refresh the dashboard. Run once:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_watchdog.ps1
$action = New-ScheduledTaskAction -Execute (Join-Path $PSScriptRoot 'vps_watchdog.bat')
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(3) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName 'FTWatchdog' -Action $action -Trigger $trigger -Force | Out-Null
Write-Host 'FTWatchdog registered: runs every 30 min (next run within ~33 min).'
