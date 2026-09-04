param(
    [string]$TaskName = 'DroneLiteratureScout',
    [string]$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string[]]$StartTimes = @('10:00', '20:00'),
    [ValidateSet('DAILY', 'HOURLY')]
    [string]$Schedule = 'DAILY',
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$Runner = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'scripts\run_cycle.ps1'

if ($WhatIf) {
    Write-Output "[WHATIF] Would register task '$TaskName' with runner '$Runner' and schedule '$Schedule' at '$($StartTimes -join ', ')'."
    exit 0
}

$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument ("-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -WorkspaceRoot `"$WorkspaceRoot`"")
$triggers = if ($Schedule -eq 'HOURLY') {
    New-ScheduledTaskTrigger -Once -At (Get-Date $StartTimes[0]) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
} else {
    foreach ($StartTime in $StartTimes) {
        New-ScheduledTaskTrigger -Daily -At (Get-Date $StartTime)
    }
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Description 'Run the UAV literature-scout local cycle plumbing.' -Force | Out-Null
Write-Output "[OK] Registered '$TaskName'. The task runs one cycle per trigger and does not keep a resident search loop."
