# Patch chart03.chr inputs to v1.01 (run on VPS while terminal64 is STOPPED).
$ErrorActionPreference = "Stop"
$d = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Profiles\Charts\FTTest\chart03.chr"
$t = [System.IO.File]::ReadAllText($d)
$t = $t -replace "InpGridStepPts=350", "InpGridStepPts=500"
if ($t -notmatch "InpLayerCooldownSec") {
  $t = $t -replace "(InpGridStepPts=500\r?\n)", "`$1InpLayerCooldownSec=1200`r`nInpReentryDelaySec=900`r`n"
}
[System.IO.File]::WriteAllText($d, $t)
Select-String -Path $d -Pattern "InpGridStepPts=|InpLayerCooldown|InpReentryDelay|InpMagic="
