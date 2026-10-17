# Build chart03.chr (GridBestRREA, magic 930023) from chart01.chr template.
# Run on VPS while terminal64 is STOPPED.
$ErrorActionPreference = "Stop"
$dir = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Profiles\Charts\FTTest"
$src = Join-Path $dir "chart01.chr"
$dst = Join-Path $dir "chart03.chr"
$t = [System.IO.File]::ReadAllText($src)
if ($t -notmatch "InpMagic=930021") { throw "template unexpected: no InpMagic=930021" }
$t = $t -replace "id=1790837995000000007", "id=1790837997000000007"
$t = $t -replace "name=GridRecoveryEA", "name=GridBestRREA"
$t = $t -replace "path=Experts\\FTTest\\GridRecoveryEA\.ex5", "path=Experts\FTTest\GridBestRREA.ex5"
$newInputs = "<inputs>`r`nInpMode=3`r`nInpLots=0.01`r`nInpLotMult=2.0`r`nInpGridStepPts=500`r`nInpLayerCooldownSec=1200`r`nInpReentryDelaySec=900`r`nInpTPDistPts=180`r`nInpMaxLayers=6`r`nInpMaxLots=0.0`r`nInpMagic=930023`r`nInpTrendTF=16385`r`nInpTrendMAPeriod=200`r`nInpWaitFlatOnFlip=true`r`nInpSLBufferPts=100`r`nInpAllowReal=false`r`nInpEquityStopMoney=5000.0`r`nInpDeviationPts=50`r`n</inputs>"  # v1.01: $5 step + 20-min layer cooldown + 15-min re-entry gate
$t = [regex]::Replace($t, "(?s)<inputs>.*?</inputs>", $newInputs)
$t = $t -replace "window_left=0", "window_left=320"
$t = $t -replace "window_top=0", "window_top=340"
[System.IO.File]::WriteAllText($dst, $t)
Write-Output "wrote chart03.chr"
Select-String -Path $dst -Pattern "name=|path=Experts|InpMagic=|id=" | ForEach-Object { $_.Line }
