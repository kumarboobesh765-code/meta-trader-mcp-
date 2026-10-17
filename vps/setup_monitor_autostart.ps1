# Makes the VPS Telegram monitor permanent and crash-proof. Run over SSH as
# Administrator:
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\FTTest\scripts\setup_monitor_autostart.ps1
#
# Design: run C:\VPSMonitor\monitor.ps1 as a HIDDEN background task (session 0),
# because visible windows are killed whenever an RDP session connects/disconnects
# (Last Result 0xC000013A = console closed). The task:
#   - starts at boot AND at logon (duplicate starts are ignored while running)
#   - has NO execution time limit (no 72-hour auto-kill)
#   - auto-restarts 1 minute after any crash
#   - runs as Administrator via S4U (no stored password)
# Monitor activity stays visible in C:\VPSMonitor\monitor.log.

$ErrorActionPreference = "Stop"

Write-Host "== stopping existing monitor instances =="
Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
    Where-Object { $_.CommandLine -like "*VPSMonitor\monitor.ps1*" } |
    ForEach-Object {
        Write-Host ("   killing PID " + $_.ProcessId)
        Stop-Process -Id $_.ProcessId -Force
    }

Write-Host "== registering scheduled task 'VPSMonitor' (hidden, durable) =="
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\VPSMonitor\monitor.ps1" `
    -WorkingDirectory "C:\VPSMonitor"
$triggers = @(
    New-ScheduledTaskTrigger -AtStartup
    New-ScheduledTaskTrigger -AtLogOn
)
$principal = New-ScheduledTaskPrincipal -UserId "Administrator" -LogonType S4U -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "VPSMonitor" -Force `
    -Action $action -Trigger $triggers -Principal $principal -Settings $settings | Out-Null

# S4U tasks can start immediately without waiting for a trigger:
Write-Host "== starting the task now =="
Start-ScheduledTask -TaskName "VPSMonitor"
Start-Sleep -Seconds 5

Write-Host "== done =="
Get-ScheduledTask -TaskName "VPSMonitor" | Format-List TaskName, State
Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
    Where-Object { $_.CommandLine -like "*VPSMonitor\monitor.ps1*" } |
    ForEach-Object { Write-Host ("   running: PID " + $_.ProcessId) }
