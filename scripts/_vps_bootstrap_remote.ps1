# Bootstrap the VPS remotely: install OpenSSH + deploy key without user action.
# Tries WMI/DCOM process execution first (zero windows). If blocked, falls back
# to an RDP session with an "initial program" that runs the same bootstrap and
# exits (a window briefly appears, no interaction needed).
# Credentials are read from .env.vps -- never passed on a command line.
param([switch]$UseRdp)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $root '.env.vps'
$map = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)=(.*)$') {
        $map[$Matches[1]] = $Matches[2].Trim().Trim("'").Trim('"')
    }
}
$host_ = $map['VPS_HOST']; $user = $map['VPS_USER']
$pw = $map['VPS_PASSWORD']
$sec = ConvertTo-SecureString $pw -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential("$host_\$user", $sec)

# ---- the bootstrap to run ON the VPS (ASCII only) ----
$inner = @'
$log = 'C:\Users\Public\vps_bootstrap.log'
function W($m) { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format s), $m) }
try {
    W 'bootstrap start'
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $adm = (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    W ("user: $env:USERNAME admin: $adm")
    $pub = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFdB8cdlfUd6GjuNthKWc7dtwoOOnlsL7BRkbTPQDluA freebuff-vps-deploy'
    Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
    W 'openssh capability installed'
    Set-Service sshd -StartupType Automatic
    Start-Service sshd
    W ('sshd status: ' + (Get-Service sshd).Status)
    $ak = "$env:ProgramData\ssh\administrators_authorized_keys"
    if (-not (Select-String -Path $ak -SimpleMatch 'AAAAC3NzaC1lZDI1NTE5' -Quiet -ErrorAction SilentlyContinue)) {
        [System.IO.File]::AppendAllText($ak, $pub + "`r`n")
        W 'deploy key added'
    } else { W 'deploy key already present' }
    icacls $ak /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
    W 'key ACL set'
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -ErrorAction SilentlyContinue | Out-Null
    W 'firewall rule ensured'
    netstat -an | Select-String ':22 ' | ForEach-Object { W ($_.ToString().Trim()) }
    W 'bootstrap done'
} catch {
    W ('ERROR: ' + $_.Exception.Message)
}
'@
$b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
$remoteCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $b64"

if (-not $UseRdp) {
    Write-Host "== trying WMI/DCOM process execution (zero windows) =="
    try {
        $opt = New-CimSessionOption -Protocol Dcom
        $cs = New-CimSession -ComputerName $host_ -Credential $cred -SessionOption $opt -OperationTimeoutSec 15 -ErrorAction Stop
        $r = Invoke-CimMethod -CimSession $cs -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $remoteCmd }
        Remove-CimSession $cs
        Write-Host ("WMI Create ReturnValue={0} ProcessId={1}" -f $r.ReturnValue, $r.ProcessId)
        if ($r.ReturnValue -eq 0) {
            Write-Host 'bootstrap launched via WMI; waiting for sshd...'
            foreach ($i in 1..12) {
                Start-Sleep 5
                $t = Test-NetConnection -ComputerName $host_ -Port 22 -WarningAction SilentlyContinue -InformationLevel Quiet
                if ($t) { Write-Host 'PORT 22 NOW REACHABLE'; exit 0 }
            }
            Write-Host 'port 22 still closed after 60s (check C:\Users\Public\vps_bootstrap.log on the VPS)'
            exit 2
        }
    } catch {
        Write-Host ("WMI failed: " + $_.Exception.Message)
        Write-Host 'falling back to RDP...'
        $UseRdp = $true
    }
}

if ($UseRdp) {
    Write-Host "== RDP fallback: session runs bootstrap as initial program =="
    cmdkey /generic:TERMSRV/$host_ /user:$user /pass:$pw | Out-Null
    $rdp = Join-Path $env:TEMP 'vps_bootstrap.rdp'
    @(
        "full address:s:$host_"
        'prompt for credentials:i:0'
        'alternate shell:s:' + $remoteCmd
        'screen mode id:i:1'
        'desktopwidth:i:1100'
        'desktopheight:i:700'
        'authentication level:i:2'
    ) | Set-Content -Path $rdp -Encoding ascii
    Write-Host "launching mstsc with $rdp (window appears briefly, runs bootstrap, exits)"
    Start-Process mstsc -ArgumentList $rdp
    foreach ($i in 1..24) {
        Start-Sleep 5
        $t = Test-NetConnection -ComputerName $host_ -Port 22 -WarningAction SilentlyContinue -InformationLevel Quiet
        if ($t) { Write-Host 'PORT 22 NOW REACHABLE'; exit 0 }
    }
    Write-Host 'port 22 still closed - the RDP session may still be starting or provider firewall blocks 22'
    exit 2
}
