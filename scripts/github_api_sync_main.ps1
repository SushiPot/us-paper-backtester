param(
    [string]$Repository = "SushiPot/us-paper-backtester",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

function Invoke-GhJson {
    param(
        [string]$Path,
        [string]$Method = "GET",
        [object]$Body = $null
    )

    if ($null -eq $Body) {
        return gh api $Path --method $Method | ConvertFrom-Json
    }

    $Json = $Body | ConvertTo-Json -Depth 12
    return $Json | gh api $Path --method $Method --input - | ConvertFrom-Json
}

Write-Host "[FALLBACK] Git HTTPS push failed; trying GitHub API sync."
Write-Host "[FALLBACK] Repository: $Repository"
Write-Host "[FALLBACK] Branch: $Branch"

$GhVersion = gh --version
if (-not $GhVersion) {
    throw "GitHub CLI is not available."
}

$Status = git status --porcelain
if ($Status) {
    throw "Working tree is not clean. Commit or discard local changes before API sync."
}

$RemoteRef = Invoke-GhJson -Path "repos/$Repository/git/ref/heads/$Branch"
$RemoteSha = [string]$RemoteRef.object.sha
$RemoteCommit = Invoke-GhJson -Path "repos/$Repository/git/commits/$RemoteSha"
$RemoteTreeSha = [string]$RemoteCommit.tree.sha
$LocalHead = (git rev-parse HEAD).Trim()
$LocalTreeSha = (git rev-parse "HEAD^{tree}").Trim()
$LocalMessage = (git show --quiet --format=%s HEAD).Trim()

Write-Host "[FALLBACK] Local HEAD:  $LocalHead"
Write-Host "[FALLBACK] Remote HEAD: $RemoteSha"

if ($RemoteSha -eq $LocalHead) {
    Write-Host "[OK] GitHub already points to the local commit."
    exit 0
}

if ($RemoteTreeSha -eq $LocalTreeSha) {
    Write-Host "[OK] GitHub already has the same file contents."
    Write-Host "[INFO] Local git may still show ahead until normal git fetch works again."
    exit 0
}

$TrackedFiles = git ls-files
if (-not $TrackedFiles) {
    throw "No tracked files found."
}

$TreeEntries = New-Object System.Collections.Generic.List[object]
foreach ($Path in $TrackedFiles) {
    $Mode = "100644"
    $Bytes = [System.IO.File]::ReadAllBytes((Join-Path (Get-Location) $Path))
    $Content = [System.Text.Encoding]::UTF8.GetString($Bytes)
    $TreeEntries.Add(
        @{
            path = $Path.Replace("\", "/")
            mode = $Mode
            type = "blob"
            content = $Content
        }
    )
}

$Tree = Invoke-GhJson -Path "repos/$Repository/git/trees" -Method "POST" -Body @{ tree = $TreeEntries }
$Commit = Invoke-GhJson -Path "repos/$Repository/git/commits" -Method "POST" -Body @{
    message = $LocalMessage
    tree = [string]$Tree.sha
    parents = @($RemoteSha)
}
$UpdatedRef = Invoke-GhJson -Path "repos/$Repository/git/refs/heads/$Branch" -Method "PATCH" -Body @{
    sha = [string]$Commit.sha
    force = $false
}

Write-Host "[OK] GitHub API sync completed."
Write-Host "[OK] Remote commit: $($UpdatedRef.object.sha)"
Write-Host "[INFO] Local git may still show ahead until normal git fetch works again."
