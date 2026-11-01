param(
    [int]$CacheLimit = -1,
    [switch]$ForceLocalPaper,
    [switch]$SkipTests,
    [switch]$IncludeWeeklyResearch,
    [switch]$IncludeOnlineScan,
    [switch]$SkipPrediction,
    [switch]$LegacyPaper,
    [switch]$FullTests
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$ProjectDir = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

. "$PSScriptRoot\python_env.ps1"
$Python = Resolve-ProjectPython

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogDir "scheduled_self_update_$Stamp.log"

$ArgsList = @("self_update_main.py", "--cache-limit", $CacheLimit.ToString())
if (-not $LegacyPaper) {
    $ArgsList += "--daily"
}
if ($FullTests) {
    $ArgsList += "--full-tests"
}
if (-not $SkipPrediction) {
    $ArgsList += "--with-prediction"
}
if (-not $IncludeWeeklyResearch) {
    $ArgsList += "--skip-weekly-research"
}
if (-not $IncludeOnlineScan) {
    $ArgsList += "--skip-online-scan"
}
if ($ForceLocalPaper -and $LegacyPaper) {
    $ArgsList += "--force-local-paper"
}
if ($SkipTests) {
    $ArgsList += "--skip-tests"
}

Set-Location $ProjectDir

"[START] $(Get-Date -Format o) scheduled self update" | Tee-Object -FilePath $LogPath
"[INFO] Project: $ProjectDir" | Tee-Object -FilePath $LogPath -Append
"[INFO] Python: $Python" | Tee-Object -FilePath $LogPath -Append
"[INFO] Args: $($ArgsList -join ' ')" | Tee-Object -FilePath $LogPath -Append

function Test-PredictionNetworkRecovery {
    param([datetimeoffset]$AttemptStarted)
    try {
        $Status = Get-Content -LiteralPath (Join-Path $ProjectDir 'outputs/prediction/status.json') -Raw | ConvertFrom-Json
        $Network = Get-Content -LiteralPath (Join-Path $ProjectDir 'data_cache/prediction/network_state.json') -Raw | ConvertFrom-Json
        $Updated = [datetimeoffset]::Parse($Status.updated_at)
        $Until = [datetimeoffset]::Parse($Network.until)
        $Now = [datetimeoffset]::UtcNow
        return ($Status.status -eq 'STALE_DATA' -and $Status.data_ready -is [bool] -and -not $Status.data_ready `
            -and $Updated -ge $AttemptStarted -and $Updated -le $Now.AddMinutes(5) `
            -and $Until -gt $Now -and -not [string]::IsNullOrWhiteSpace($Network.reason))
    }
    catch {
        return $false
    }
}

for ($Attempt = 1; $Attempt -le 2; $Attempt++) {
    $AttemptStarted = [datetimeoffset]::UtcNow
    "[ATTEMPT] $Attempt at $($AttemptStarted.ToString('o'))" | Tee-Object -FilePath $LogPath -Append
    try {
        # Windows PowerShell treats native stderr as an ErrorRecord, even for warnings.
        $ErrorActionPreference = "Continue"
        & $Python @ArgsList 2>&1 | ForEach-Object { $_.ToString() } |
            Tee-Object -FilePath $LogPath -Append -ErrorAction Stop
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = "Stop"
    }
    if ($ExitCode -eq 0 -or $Attempt -eq 2 -or $LegacyPaper -or $SkipPrediction `
        -or -not (Test-PredictionNetworkRecovery -AttemptStarted $AttemptStarted)) {
        break
    }
    "[RECOVERY] Network cooldown detected; waiting 3600 seconds before one final attempt. Downloader cooldown still applies." |
        Tee-Object -FilePath $LogPath -Append
    Start-Sleep -Seconds 3600
}

if ($ExitCode -eq 0) {
    "[OK] $(Get-Date -Format o) scheduled self update completed" | Tee-Object -FilePath $LogPath -Append
}
else {
    "[ERROR] $(Get-Date -Format o) scheduled self update failed with exit code $ExitCode" |
        Tee-Object -FilePath $LogPath -Append
}

exit $ExitCode
