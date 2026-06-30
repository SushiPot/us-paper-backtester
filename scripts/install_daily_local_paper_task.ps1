param(
    [string]$TaskName = "US Paper Backtester Daily Run",
    [string]$RunAt = "06:30"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
. "$PSScriptRoot\python_env.ps1"
$Python = Resolve-ProjectPython

$Action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "local_paper_main.py --once" `
    -WorkingDirectory $ProjectDir

$Trigger = New-ScheduledTaskTrigger -Daily -At $RunAt
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Run the local US paper trading simulation once per day." `
    -Force

Write-Host "Scheduled task installed: $TaskName"
Write-Host "Project directory: $ProjectDir"
Write-Host "Python executable: $Python"
Write-Host "Daily run time: $RunAt"
