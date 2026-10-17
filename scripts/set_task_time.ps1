# Recreate MetaTraderRepoAutoPush at daily 18:30, safe for paths with spaces.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$bat = Join-Path $repo "scripts\auto_push.bat"

schtasks /Delete /TN "MetaTraderRepoAutoPush" /F 2>$null | Out-Null

$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"`"$bat`"`""
$trigger = New-ScheduledTaskTrigger -Daily -At "18:30"
Register-ScheduledTask -TaskName "MetaTraderRepoAutoPush" `
    -Action $action -Trigger $trigger -Force | Out-Null

$t    = Get-ScheduledTask -TaskName "MetaTraderRepoAutoPush"
$info = Get-ScheduledTaskInfo -TaskName "MetaTraderRepoAutoPush"
Write-Output ("NextRunTime: " + $info.NextRunTime)
Write-Output ("State: " + $t.State)
Write-Output ("Execute: " + $t.Actions[0].Execute)
Write-Output ("Arguments: " + $t.Actions[0].Arguments)
