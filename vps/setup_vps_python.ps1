# Install Python + MetaTrader5 package on the VPS (for the forward-test runner).
# Run over SSH: powershell -ExecutionPolicy Bypass -File setup_vps_python.ps1
$ErrorActionPreference = 'Stop'
$ver = '3.14.7'
$py = 'C:\Program Files\Python314\python.exe'

if (-not (Test-Path $py)) {
    $exe = 'C:\Users\Public\python-setup.exe'
    Write-Host "downloading Python $ver..."
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe" -OutFile $exe
    Write-Host 'installing silently (all users, PATH)...'
    Start-Process -FilePath $exe -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0' -Wait
}
& $py --version
& $py -m pip install --quiet --upgrade pip
& $py -m pip install MetaTrader5
& $py -c "import MetaTrader5; print('MetaTrader5 import OK')"
