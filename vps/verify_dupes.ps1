# Check for duplicate terminals + current chart03 inputs on disk.
$ErrorActionPreference = "Continue"
Write-Output "=== terminal64 processes ==="
Get-Process terminal64 | Select-Object Id, StartTime
Write-Output "=== chart03 inputs on disk ==="
$d = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Profiles\Charts\FTTest\chart03.chr"
Select-String -Path $d -Pattern "InpGridStepPts=|InpLayerCooldown|InpReentryDelay|InpMagic=|InpTPDistPts="
