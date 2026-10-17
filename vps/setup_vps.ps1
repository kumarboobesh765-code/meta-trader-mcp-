# One-time VPS setup for headless FTTestEA deployment.
# Run INSIDE the RDP session as Administrator:
#   powershell -ExecutionPolicy Bypass -File setup_vps.ps1
# Enables SSH access and (optionally) auto-logon + MT5 startup.
# This script NEVER launches MetaTrader itself.
$ErrorActionPreference = 'Stop'

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error 'Run this script as Administrator (right-click PowerShell -> Run as administrator).'
}

# --- 1. OpenSSH server (the headless access channel) ---
if (-not (Get-WindowsCapability -Online -Name OpenSSH.Server* |
          Where-Object State -eq 'Installed')) {
    Write-Host 'Installing OpenSSH Server...'
    Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
}
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' `
        -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound `
        -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}
Write-Host 'SSH server ready on port 22.'

# --- 2. Install the deploy public key (both locations, so admin and
#        standard accounts both work) ---
$pubFile = Join-Path $PSScriptRoot 'keys\id_ed25519_vps.pub'
if (-not (Test-Path $pubFile)) {
    Write-Error "Missing $pubFile - copy the vps\keys folder from your PC first."
}
$pub = (Get-Content $pubFile | Select-Object -First 1).Trim()

function Add-Key($file, $grant) {
    $existing = Get-Content $file -ErrorAction SilentlyContinue
    if ($existing -contains $pub) {
        Write-Host "key already present in $file"
        return
    }
    [System.IO.File]::AppendAllText($file, $pub + "`r`n")   # UTF-8 no BOM
    & icacls.exe $file /inheritance:r /grant $grant | Out-Null
    Write-Host "key installed in $file"
}
Add-Key "$env:ProgramData\ssh\administrators_authorized_keys" 'Administrators:F SYSTEM:F'
$sshDir = Join-Path $env:USERPROFILE '.ssh'
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
Add-Key (Join-Path $sshDir 'authorized_keys') "$($env:USERNAME):F"

# --- 3. Optional: Windows auto-logon (so MT5 survives VPS reboots) ---
$ans = Read-Host 'Enable Windows auto-logon (needed only if MT5 must survive reboots)? The password is stored in the registry - for a safer alternative search "Sysinternals Autologon". (y/N)'
if ($ans -eq 'y') {
    $u = Read-Host "Logon username [$($env:USERNAME)]"
    if (-not $u) { $u = $env:USERNAME }
    $sec = Read-Host 'Logon password' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $wl = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
    Set-ItemProperty $wl -Name AutoAdminLogon -Value '1'
    Set-ItemProperty $wl -Name DefaultUserName -Value $u
    Set-ItemProperty $wl -Name DefaultPassword -Value $plain
    Write-Host "auto-logon enabled for $u"
}

# --- 4. Optional: start MT5 at logon ---
$ans = Read-Host 'Add MetaTrader 5 to the Startup folder (starts at logon)? Choose No to start it manually. (y/N)'
if ($ans -eq 'y') {
    $mt5 = 'C:\Program Files\MetaTrader 5\terminal64.exe'
    if (Test-Path $mt5) {
        $ws = New-Object -ComObject WScript.Shell
        $sc = $ws.CreateShortcut("$([Environment]::GetFolderPath('Startup'))\MetaTrader 5.lnk")
        $sc.TargetPath = $mt5
        $sc.Save()
        Write-Host 'MT5 shortcut added to Startup.'
    } else {
        Write-Host "MT5 not found at $mt5 - install it, then add the shortcut yourself."
    }
}

# --- 5. Keep the session alive ---
powercfg /change standby-timeout-ac 0

Write-Host @'

SETUP DONE. Now, on your PC:
  1. copy .env.vps.example -> .env.vps and fill in VPS_HOST / VPS_USER
  2. bash scripts/vps_deploy.sh deploy
Then, on this VPS:
  3. start MetaTrader 5 MANUALLY (nobody launches it for you), log in,
     enable Algo Trading, attach FTTestEA with the presets from
     MQL5\Presets (refresh Navigator first)
  4. DISCONNECT the RDP session (click X) -- never "Sign off", or the
     session (and the EA) dies.
'@
