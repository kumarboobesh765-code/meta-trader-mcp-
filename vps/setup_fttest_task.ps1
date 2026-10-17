# Register + start the FTForwardTest runner on the VPS (in the interactive RDP
# session -- same session as MT5, so the MetaTrader5 IPC connects) and point
# MT5's last-used profile at FTTest so the 10 EA charts auto-load at startup.
# NOTE: this script never launches MetaTrader itself.
$ErrorActionPreference = 'Stop'
$root = 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075'

# --- 1. profile auto-load (safe only while MT5 is closed: it rewrites the ini
#        on exit, which would overwrite our edit) ---
if (Get-Process terminal64 -ErrorAction SilentlyContinue) {
    Write-Host 'WARNING: MT5 is running - close it and re-run so ProfileLast=FTTest sticks.'
} else {
    $ini = Join-Path $root 'config\common.ini'
    $c = Get-Content $ini -Raw
    $c = $c -replace 'ProfileLast=[^\r\n]*', 'ProfileLast=FTTest'
    Set-Content -Path $ini -Value $c -Encoding ASCII -NoNewline
    Write-Host 'common.ini: ProfileLast=FTTest'
}

# --- 2. runner persistence: interactive logon task + Startup shortcut ---
schtasks /Create /TN FTForwardTest /TR "C:\FTTest\start_fttest.bat" /SC ONLOGON /RU Administrator /IT /RL HIGHEST /F
$ws = New-Object -ComObject WScript.Shell
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'FTForwardTest.lnk'
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = 'C:\FTTest\start_fttest.bat'
$sc.WorkingDirectory = 'C:\FTTest'
$sc.WindowStyle = 7   # minimized
$sc.Save()
Write-Host "task registered + startup shortcut: $lnk"

# --- 3. start the runner now; verify it actually came up ---
schtasks /Run /TN FTForwardTest
Start-Sleep -Seconds 5
if (Test-Path 'C:\FTTest\logs\forward_test_stdout.txt') {
    Write-Host 'runner is UP (started via logon task)'
} else {
    Write-Host 'task did not fire from this session - starting detached fallback'
    Start-Process -FilePath 'C:\FTTest\start_fttest.bat' `
        -WorkingDirectory 'C:\FTTest' -WindowStyle Minimized
    Start-Sleep -Seconds 5
    if (Test-Path 'C:\FTTest\logs\forward_test_stdout.txt') {
        Write-Host 'runner is UP (detached fallback)'
    } else {
        Write-Host 'runner NOT up yet - it will start at next interactive logon'
    }
}

Write-Host '--- sessions ---'
query session
Write-Host '--- runner log ---'
Get-Content 'C:\FTTest\logs\forward_test_stdout.txt' -Tail 5 -ErrorAction SilentlyContinue
Write-Host '--- python procs ---'
Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, StartTime
