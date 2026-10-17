# Set up reliable MT5 auto-login via the documented /config: mechanism.
# Reads the password from C:\FTTest\.env (never printed), writes
# C:\FTTest\mt5_autologin.ini, and points every Startup-folder shortcut that
# launches terminal64.exe at /config:C:\FTTest\mt5_autologin.ini.
$ErrorActionPreference = "Stop"

$pw = $null
foreach ($line in Get-Content 'C:\FTTest\.env') {
    if ($line -match '^\s*password\s*=\s*(.+?)\s*$') {
        $pw = $Matches[1].Trim('"').Trim("'")
    }
}
if (-not $pw) { Write-Host 'FAIL: no password= line in C:\FTTest\.env'; exit 1 }

$iniPath = 'C:\FTTest\mt5_autologin.ini'
@(
    '[StartUp]',
    'Login=465983',
    ('Password=' + $pw),
    'Server=FusionMarkets-Demo'
) | Set-Content -Path $iniPath -Encoding ASCII
Write-Host ('wrote ' + $iniPath + ' (password length ' + $pw.Length + ', not shown)')

$ws = New-Object -ComObject WScript.Shell
$startup = [Environment]::GetFolderPath('Startup')
Get-ChildItem $startup -Filter '*.lnk' | ForEach-Object {
    $s = $ws.CreateShortcut($_.FullName)
    if ($s.TargetPath -like '*terminal64*') {
        $s.Arguments = '/config:C:\FTTest\mt5_autologin.ini'
        $s.Save()
        Write-Host ('updated shortcut: ' + $_.Name + ' -> ' + $s.TargetPath + ' ' + $s.Arguments)
    }
}
Write-Host 'done'
