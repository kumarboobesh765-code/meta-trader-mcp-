# Diagnostic for C:\VPSMonitor\monitor.ps1 — verifies the trim fix is deployed,
# checks for running instances, summarizes monitor.log, and tests the Telegram
# API end-to-end (getMe + one real test message). The token is never printed.
$ErrorActionPreference = "Continue"

Write-Host "== 1. deployed script has the Trim fix? =>"
$m = Get-Content "C:\VPSMonitor\monitor.ps1" -Raw
Write-Host ("   TrimFixPresent=" + ($m -match '\.Trim\(\)'))
Write-Host ("   ReadsTokenRawUntrimmed=" + ($m -match 'Get-Content \$tokenFile -Raw\r?\n'))

Write-Host "== 2. running monitor instances =>"
$procs = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
    Where-Object { $_.CommandLine -like "*VPSMonitor\monitor.ps1*" }
if ($procs) { $procs | ForEach-Object { Write-Host ("   PID " + $_.ProcessId + " started " + $_.CreationDate) } }
else { Write-Host "   NONE" }

Write-Host "== 3. monitor.log summary =>"
$log = Get-Content "C:\VPSMonitor\monitor.log"
Write-Host ("   alert-sent lines : " + ($log | Where-Object { $_ -like "*Telegram alert sent*" }).Count)
Write-Host ("   send-failed lines: " + ($log | Where-Object { $_ -like "*Telegram send failed*" }).Count)
Write-Host "   last 8 lines:"
$log | Select-Object -Last 8 | ForEach-Object { Write-Host ("   " + $_) }

Write-Host "== 4. telegram api test (token stays hidden) =>"
$enc = (Get-Content "C:\VPSMonitor\telegram-token.txt" -Raw).Trim()
$secure = ConvertTo-SecureString $enc
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $tok = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }

try {
    $me = Invoke-RestMethod -Uri "https://api.telegram.org/bot$($tok)/getMe" -TimeoutSec 15
    Write-Host ("   getMe ok=" + $me.ok + " bot=@" + $me.result.username)
}
catch {
    Write-Host ("   getMe FAILED: " + $_.Exception.Message)
}

try {
    $r = Invoke-RestMethod -Uri "https://api.telegram.org/bot$($tok)/sendMessage" -Method Post `
        -Body @{ chat_id = "1819206234"; text = "VPS Monitor: Telegram channel verified OK (test alert from monitor fix)" } `
        -TimeoutSec 15
    Write-Host ("   sendMessage ok=" + $r.ok + " message_id=" + $r.result.message_id)
}
catch {
    Write-Host ("   sendMessage FAILED: " + $_.Exception.Message)
}
