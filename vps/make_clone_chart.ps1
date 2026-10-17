# Build chart02.chr (SlipstreamCloneEA, magic 930022) from chart01.chr template.
# Run on VPS while terminal64 is STOPPED.
$ErrorActionPreference = "Stop"
$dir = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Profiles\Charts\FTTest"
$src = Join-Path $dir "chart01.chr"
$dst = Join-Path $dir "chart02.chr"
$t = [System.IO.File]::ReadAllText($src)
if ($t -notmatch "InpMagic=930021") { throw "template unexpected: no InpMagic=930021" }
$t = $t -replace "id=1790837995000000007", "id=1790837996000000007"
$t = $t -replace "name=GridRecoveryEA", "name=SlipstreamCloneEA"
$t = $t -replace "path=Experts\\FTTest\\GridRecoveryEA\.ex5", "path=Experts\FTTest\SlipstreamCloneEA.ex5"
$newInputs = "<inputs>`r`nInpLots=0.01`r`nInpLotMult=2.0`r`nInpGridStepPts=350`r`nInpTPDistPts=180`r`nInpMaxLayers=12`r`nInpMaxLots=0.0`r`nInpMagic=930022`r`nInpAllowReal=false`r`nInpEquityStopMoney=5000.0`r`nInpDeviationPts=50`r`n</inputs>"
$t = [regex]::Replace($t, "(?s)<inputs>.*?</inputs>", $newInputs)
$t = $t -replace "window_left=0", "window_left=796"
$t = $t -replace "window_top=0", "window_top=32"
[System.IO.File]::WriteAllText($dst, $t)
Write-Output "wrote chart02.chr"
Select-String -Path $dst -Pattern "name=|path=Experts|InpMagic=|id=" | ForEach-Object { $_.Line }
