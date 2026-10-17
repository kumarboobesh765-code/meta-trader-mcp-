# Build chart04.chr (SlipstreamAltEA, magic 930031) from chart03.chr template.
# Run on VPS while terminal64 is STOPPED.
$ErrorActionPreference = "Stop"
$dir = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Profiles\Charts\FTTest"
$src = Join-Path $dir "chart03.chr"
$dst = Join-Path $dir "chart04.chr"
$t = [System.IO.File]::ReadAllText($src)
if ($t -notmatch "GridBestRREA") { throw "template unexpected: no GridBestRREA" }
$t = $t -replace "id=1790837997000000007", "id=1790837998000000007"
$t = $t -replace "name=GridBestRREA", "name=SlipstreamAltEA"
$t = $t -replace "path=Experts\\FTTest\\GridBestRREA\.ex5", "path=Experts\FTTest\SlipstreamAltEA.ex5"
$lines = $t -split "`r`n"
$out = New-Object System.Collections.Generic.List[string]
$inInputs = $false
foreach ($l in $lines) {
  if ($l -match "^<inputs>") { $inInputs = $true
    $out.Add("<inputs>")
    $out.Add("InpLots=0.01")
    $out.Add("InpLotMult=2.0")
    $out.Add("InpGridStepPts=400")
    $out.Add("InpTPDistPts=180")
    $out.Add("InpMaxLayers=12")
    $out.Add("InpMaxLots=0.0")
    $out.Add("InpMagic=930031")
    $out.Add("InpNewsFilter=true")
    $out.Add("InpNewsPauseMin=30")
    $out.Add("InpNewsCurrency=USD")
    $out.Add("InpAllowReal=false")
    $out.Add("InpEquityStopMoney=5000.0")
    $out.Add("InpDeviationPts=50")
    continue }
  if ($l -match "^</inputs>") { $inInputs = $false; $out.Add("</inputs>"); continue }
  if (-not $inInputs) { $out.Add($l) }
}
$t = ($out -join "`r`n")
$t = $t -replace "window_left=0,", "window_left=320"
$t = $t -replace "window_top=340,", "window_top=680"
[System.IO.File]::WriteAllText($dst, $t, [System.Text.Encoding]::Unicode)
Write-Output "wrote chart04.chr"
Select-String -Path $dst -Pattern "name=SlipstreamAlt|path=Experts|InpMagic=|id=" | ForEach-Object { $_.Line }
