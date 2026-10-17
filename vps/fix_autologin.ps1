# Restore MT5 auto-login: insert Password= next to Login= in common.ini,
# taking the password from C:\FTTest\.env (it is never printed or transmitted).
$ErrorActionPreference = "Stop"
$envFile = 'C:\FTTest\.env'
$ini = 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\config\common.ini'

$pw = $null
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*password\s*=\s*(.+?)\s*$') {
        $pw = $Matches[1].Trim('"').Trim("'")
    }
}
if (-not $pw) { Write-Host 'FAIL: no password= line in C:\FTTest\.env'; exit 1 }

Copy-Item $ini ($ini + '.bak') -Force
$out = @()
$done = $false
foreach ($l in Get-Content $ini) {
    if ($l -match '^Password=') { continue }  # drop any stale entry
    $out += $l
    if (-not $done -and $l -match '^Login=') {
        $out += ('Password=' + $pw)
        $done = $true
    }
}
if (-not $done) { Write-Host 'FAIL: no Login= line in common.ini'; exit 1 }
Set-Content -Path $ini -Value $out -Encoding ASCII
Write-Host ('common.ini patched: Password=*** inserted (length ' + $pw.Length + '); backup at common.ini.bak')
