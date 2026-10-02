param(
    [int]$CacheLimit = -1,
    [switch]$ForceLocalPaper,
    [switch]$SkipTests,
    [switch]$IncludeWeeklyResearch,
    [switch]$IncludeOnlineScan
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
if (-not $IncludeWeeklyResearch) {
    $ArgsList += "--skip-weekly-research"
}
if (-not $IncludeOnlineScan) {
    $ArgsList += "--skip-online-scan"
}
if ($ForceLocalPaper) {
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

if ($ExitCode -eq 0) {
    "[OK] $(Get-Date -Format o) scheduled self update completed" | Tee-Object -FilePath $LogPath -Append
}
else {
    "[ERROR] $(Get-Date -Format o) scheduled self update failed with exit code $ExitCode" |
        Tee-Object -FilePath $LogPath -Append
}

exit $ExitCode
