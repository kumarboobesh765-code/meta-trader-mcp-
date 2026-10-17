# Makes the low-noise VPS watchdog permanent and crash-proof.
# Run ON THE VPS over SSH:
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\FTTest\scripts\setup_vps_watchdog.ps1
#
# Task: hidden session-0 PowerShell wrapper (SSH-safe, survives RDP
# connect/disconnect), no execution time limit, auto-restart 1 min after a
# crash, starts at boot AND logon. Duplicates are ignored while running.
# The wrapper relaunches python if the script ever exits, so only a machine
# reboot needs the scheduled task itself.

$ErrorActionPreference = "Stop"

# Wrapper is written VERBATIM from a single-quoted here-string: no string
# interpolation anywhere (interpolation-based generation produced a broken
# multi-line $py once already). Short 8.3 python path = no embedded quotes.
$dst = "C:\FTTest\scripts\vps_watchdog_wrapper.ps1"
$wrapper = @'
$ErrorActionPreference = "SilentlyContinue"
while ($true) {
  & C:\PROGRA~1\Python314\python.exe C:\FTTest\scripts\vps_watchdog.py *>> C:\FTTest\logs\vps_watchdog_stdout.txt
  Start-Sleep -Seconds 10
}
'@
Set-Content -Path $dst -Value $wrapper -Encoding ASCII

Write-Host "== stopping existing watchdog/monitor instances =="
# NOTE: pattern must NOT match this setup script's own name (self-kill) --
# match the python entrypoint only, plus the legacy chatty monitor loop.
foreach ($pat in @("*vps_watchdog.py*", "*vps_watchdog_wrapper.ps1*", "*VPSMonitor\monitor.ps1*")) {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'powershell.exe'" |
        Where-Object { $_.CommandLine -like $pat } |
        ForEach-Object {
            Write-Host ("   killing PID " + $_.ProcessId + " (" + $pat + ")")
            Stop-Process -Id $_.ProcessId -Force
        }
}

Write-Host "== registering scheduled task 'VPSWatchdog' (hidden, durable) =="
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $dst" `
    -WorkingDirectory "C:\FTTest\scripts"
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

Register-ScheduledTask -TaskName "VPSWatchdog" -Force `
    -Action $action -Trigger $triggers -Principal $principal -Settings $settings | Out-Null

Write-Host "== starting the task now =="
Start-ScheduledTask -TaskName "VPSWatchdog"
Start-Sleep -Seconds 5

Write-Host "== done =="
Get-ScheduledTask -TaskName "VPSWatchdog" | Format-List TaskName, State
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*vps_watchdog.py*" } |
    ForEach-Object { Write-Host ("   running: PID " + $_.ProcessId) }
