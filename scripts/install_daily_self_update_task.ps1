param(
    [string]$TaskName = "US Paper Backtester Daily Self Update",
    [string]$RunAt = "06:30",
    [int]$CacheLimit = -1,
    [switch]$NoForceLocalPaper,
    [switch]$SkipTests,
    [switch]$IncludeWeeklyResearch,
    [switch]$IncludeOnlineScan,
    [switch]$LegacyPaper,
    [switch]$FullTests
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $PSScriptRoot "run_scheduled_self_update.ps1"
$ForceLocalPaper = $LegacyPaper -and -not $NoForceLocalPaper

if (-not (Test-Path $Runner)) {
    throw "Scheduled self-update runner was not found: $Runner"
}

$ActionArgs = @(
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$Runner`"",
    "-CacheLimit", $CacheLimit.ToString()
)
if ($ForceLocalPaper) {
    $ActionArgs += "-ForceLocalPaper"
}
if ($LegacyPaper) {
    $ActionArgs += "-LegacyPaper"
}
if ($FullTests) {
    $ActionArgs += "-FullTests"
}
if ($SkipTests) {
    $ActionArgs += "-SkipTests"
}
if ($IncludeWeeklyResearch) {
    $ActionArgs += "-IncludeWeeklyResearch"
}
if ($IncludeOnlineScan) {
    $ActionArgs += "-IncludeOnlineScan"
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ($ActionArgs -join " ") `
    -WorkingDirectory $ProjectDir

$Trigger = New-ScheduledTaskTrigger -Daily -At $RunAt
$RetrySettings = @{}
if (-not $LegacyPaper) {
    $RetrySettings.RestartCount = 1
    $RetrySettings.RestartInterval = New-TimeSpan -Hours 1
}
$Settings = New-ScheduledTaskSettingsSet `
    @RetrySettings `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Run US Paper Backtester self_update_main.py once per day with logs." `
    -Force

Write-Host "Scheduled task installed: $TaskName"
Write-Host "Project directory: $ProjectDir"
Write-Host "Runner: $Runner"
Write-Host "Daily run time: $RunAt"
Write-Host "Failure recovery: $($Settings.RestartCount) retry; interval $($Settings.RestartInterval)"
Write-Host "Cache limit: $CacheLimit"
Write-Host "Force local paper: $ForceLocalPaper"
Write-Host "Skip tests: $($SkipTests.IsPresent)"
Write-Host "Include weekly research: $($IncludeWeeklyResearch.IsPresent)"
Write-Host "Include online scan: $($IncludeOnlineScan.IsPresent)"
Write-Host "Logs: $(Join-Path $ProjectDir "logs")"
