# Make MetaTrader 5 start automatically when Windows starts on the VPS
# (explicitly requested by the user for unattended 24/7 trading).
# - Windows auto-logon (MT5 is a GUI app: an interactive session must exist)
# - MetaTrader 5 shortcut in the Startup folder
# - disables sleep so the box never pauses trading
#
# Usage: powershell -ExecutionPolicy Bypass -File setup_autostart.ps1 -Pass <admin password>
# NOTE: this script configures auto-start but never launches MT5 right now.
param(
    [Parameter(Mandatory = $true)][string]$Pass
)
$ErrorActionPreference = 'Stop'

# --- 1. Windows auto-logon (needed so the interactive session exists after a
#        reboot with nobody at the keyboard) ---
$wl = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
Set-ItemProperty $wl -Name AutoAdminLogon -Value '1'
Set-ItemProperty $wl -Name DefaultUserName -Value 'Administrator'
Set-ItemProperty $wl -Name DefaultPassword -Value $Pass
Write-Host 'auto-logon enabled for Administrator'

# --- 2. MetaTrader 5 in the Startup folder (starts at every logon) ---
$ws = New-Object -ComObject WScript.Shell
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'MetaTrader 5.lnk'
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = 'C:\Program Files\MetaTrader 5\terminal64.exe'
$sc.WorkingDirectory = 'C:\Program Files\MetaTrader 5'
$sc.WindowStyle = 1
$sc.Save()
Write-Host "MT5 auto-start shortcut: $lnk"

# --- 3. never sleep ---
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
Write-Host 'sleep/hibernate disabled'

Write-Host @'

AUTOSTART CONFIGURED. From now on, every Windows start on this VPS:
  1. Windows auto-logons Administrator
  2. MetaTrader 5 starts and loads the FTTest profile (10 EA charts)
  3. FTForwardTest (Python runner) starts and attaches
Everything runs unattended. To activate NOW: reboot once, or start
MetaTrader 5 manually this one time.

SECURITY NOTE: the auto-logon password is stored in the Winlogon registry
(DefaultPassword). For LSA-encrypted storage instead, use Sysinternals
Autologon. If you rotate the Administrator password later, update autologon
too or the VPS will sit at the logon screen after a reboot.
'@
