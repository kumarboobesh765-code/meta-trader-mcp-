# Why do VPSMonitor instances die within ~90s? Inspect sessions, process
# command lines, and Task Scheduler / logon event history.
$ErrorActionPreference = "Continue"

Write-Host "== sessions =="
query session 2>&1 | ForEach-Object { Write-Host ("   " + $_) }

Write-Host "== all powershell/cmd/wscript processes =="
Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe' OR Name = 'cmd.exe' OR Name = 'wscript.exe' OR Name = 'conhost.exe'" |
    ForEach-Object {
        $cl = $_.CommandLine
        if ($cl -and $cl.Length -gt 160) { $cl = $cl.Substring(0, 160) + "..." }
        Write-Host ("   PID " + $_.ProcessId + " [" + $_.Name + "] parent=" + $_.ParentProcessId + " start=" + $_.CreationDate + "  " + $cl)
    }

Write-Host "== VPSMonitor task status =="
schtasks /Query /TN VPSMonitor /FO LIST /V 2>&1 |
    Select-String "Next Run|Status:|Last Run|Last Result|Start When|Stop Task|Run As" |
    ForEach-Object { Write-Host ("   " + $_.ToString().Trim()) }

Write-Host "== TaskScheduler operational log (last 25 events) =="
try {
    Get-WinEvent -LogName "Microsoft-Windows-TaskScheduler/Operational" -MaxEvents 25 -ErrorAction Stop |
        ForEach-Object { Write-Host ("   " + $_.TimeCreated.ToString("HH:mm:ss") + " id=" + $_.Id + " " + (($_.Message -split "`n")[0])) }
}
catch { Write-Host ("   (unavailable: " + $_.Exception.Message + ")") }

Write-Host "== security logon/logoff events (last 20) =="
try {
    Get-WinEvent -FilterHashtable @{ LogName = "Security"; Id = 4624, 4634, 4647; StartTime = (Get-Date).AddMinutes(-30) } -MaxEvents 20 -ErrorAction Stop |
        ForEach-Object { Write-Host ("   " + $_.TimeCreated.ToString("HH:mm:ss") + " id=" + $_.Id + " " + (($_.Message -split "`n")[0])) }
}
catch { Write-Host ("   (unavailable: " + $_.Exception.Message + ")") }
