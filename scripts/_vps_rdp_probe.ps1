# RDP probe with local-drive redirection: re-runs the (idempotent) bootstrap on
# the VPS as an "initial program", then copies the resulting log back to this
# PC via \\tsclient -> C:\Users\Public\vps_bootstrap.log. No human interaction.
# The redirected drive is readable by the VPS only while this session is open.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$map = @{}
Get-Content (Join-Path $root '.env.vps') | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)=(.*)$') {
        $map[$Matches[1]] = $Matches[2].Trim().Trim("'").Trim('"')
    }
}
$host_ = $map['VPS_HOST']; $user = $map['VPS_USER']; $pw = $map['VPS_PASSWORD']
cmdkey /generic:TERMSRV/$host_ /user:$user /pass:$pw | Out-Null

$inner = @'
$log = 'C:\Users\Public\vps_bootstrap.log'
function W($m) { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format s), $m) }
try {
    W 'probe start'
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $adm = (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    W ("user: $env:USERNAME admin: $adm")
    W ('sshd service: ' + (Get-Service sshd -ErrorAction SilentlyContinue).Status)
    $cap = Get-WindowsCapability -Online -Name OpenSSH.Server* -ErrorAction SilentlyContinue
    W ('openssh capability state: ' + $cap.State)
    if ($cap.State -ne 'Installed') {
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
        W 'openssh capability installed now'
    }
    Set-Service sshd -StartupType Automatic
    Start-Service sshd
    W ('sshd status: ' + (Get-Service sshd).Status)
    $pub = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFdB8cdlfUd6GjuNthKWc7dtwoOOnlsL7BRkbTPQDluA freebuff-vps-deploy'
    $ak = "$env:ProgramData\ssh\administrators_authorized_keys"
    if (-not (Select-String -Path $ak -SimpleMatch 'AAAAC3NzaC1lZDI1NTE5' -Quiet -ErrorAction SilentlyContinue)) {
        [System.IO.File]::AppendAllText($ak, $pub + "`r`n"); W 'deploy key added'
    } else { W 'deploy key already present' }
    icacls $ak /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -ErrorAction SilentlyContinue | Out-Null
    netstat -an | Select-String ':22 ' | ForEach-Object { W ($_.ToString().Trim()) }
    $t = Test-NetConnection -ComputerName localhost -Port 22 -WarningAction SilentlyContinue
    W ('local port 22 reachable: ' + $t.TcpTestSucceeded)
    W ('external check IP: ' + (Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 10 -ErrorAction SilentlyContinue))
    W 'probe done'
} catch {
    W ('ERROR: ' + $_.Exception.Message)
}
Copy-Item $log '\\tsclient\C\Users\Public\vps_bootstrap.log' -Force -ErrorAction SilentlyContinue
'@
$b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))

$rdp = Join-Path $env:TEMP 'vps_probe.rdp'
@(
    "full address:s:$host_"
    'prompt for credentials:i:0'
    'authentication level:i:0'
    'redirectclipboard:i:0'
    'drivestoredirect:s:*'
    'redirectdrives:i:1'
    ('alternate shell:s:powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand ' + $b64)
) | Set-Content -Path $rdp -Encoding ascii

$localLog = 'C:\Users\Public\vps_bootstrap.log'
Remove-Item $localLog -ErrorAction SilentlyContinue
Write-Host 'launching RDP probe (window opens briefly, runs, copies log back, closes)'
Start-Process mstsc -ArgumentList $rdp
foreach ($i in 1..36) {
    Start-Sleep 5
    if (Test-Path $localLog) {
        Write-Host "== log retrieved from VPS =="
        Get-Content $localLog
        exit 0
    }
}
Write-Host 'no log came back after 180s'
exit 2
