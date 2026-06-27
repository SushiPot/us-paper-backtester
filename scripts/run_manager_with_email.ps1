param(
    [ValidateSet("local", "online", "ai")]
    [string]$Mode = "local",
    [switch]$SkipLocalPaper,
    [switch]$SkipResearch,
    [string]$SmtpHost = "smtp.qq.com",
    [string]$SmtpPort = "587",
    [string]$SmtpUsername = "",
    [string]$EmailFrom = "",
    [string]$EmailTo = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonPath = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
. "$PSScriptRoot\email_profile.ps1"

if (-not (Test-Path $PythonPath)) {
    throw "Bundled Python not found: $PythonPath"
}

$PasswordPtr = [IntPtr]::Zero

try {
    $PasswordPtr = Initialize-ProjectEmailEnvironment `
        -SmtpHost $SmtpHost `
        -SmtpPort $SmtpPort `
        -SmtpUsername $SmtpUsername `
        -EmailFrom $EmailFrom `
        -EmailTo $EmailTo

    $ArgsList = @("agents_main.py", "--once", "--mode", $Mode)
    if ($SkipLocalPaper) {
        $ArgsList += "--skip-local-paper"
    }
    if ($SkipResearch) {
        $ArgsList += "--skip-research"
    }

    Set-Location $ProjectRoot
    & $PythonPath @ArgsList
}
finally {
    Clear-ProjectEmailSecret -PasswordPtr $PasswordPtr
}
