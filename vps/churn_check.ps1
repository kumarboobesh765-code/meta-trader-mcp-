# Why did MT5 networking die? Check logon churn (with logon types) + sessions.
$ErrorActionPreference = 'Continue'

Write-Host '== sessions =='
query session 2>&1 | ForEach-Object { Write-Host ('   ' + $_) }

Write-Host '== logon events (last 15 min) =='
try {
    $evs = Get-WinEvent -FilterHashtable @{ LogName = 'Security'; Id = 4624, 4634, 4647; StartTime = (Get-Date).AddMinutes(-15) } -MaxEvents 40 -ErrorAction Stop
    foreach ($e in $evs) {
        $lt = ''
        if ($e.Id -eq 4624) { $lt = ' LogonType=' + $e.Properties[8].Value }
        Write-Host ('   ' + $e.TimeCreated.ToString('HH:mm:ss') + ' id=' + $e.Id + $lt)
    }
}
catch { Write-Host ('   (unavailable: ' + $_.Exception.Message + ')') }

Write-Host '== terminal64 / python processes =='
Get-CimInstance Win32_Process -Filter "Name = 'terminal64.exe' OR Name = 'python.exe'" |
    ForEach-Object {
        $cl = $_.CommandLine
        if ($cl -and $cl.Length -gt 100) { $cl = $cl.Substring(0, 100) }
        Write-Host ('   PID ' + $_.ProcessId + ' [' + $_.Name + '] session=' + $_.SessionId + ' start=' + $_.CreationDate + '  ' + $cl)
    }
