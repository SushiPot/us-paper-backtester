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
. "$PSScriptRoot\python_env.ps1"
. "$PSScriptRoot\email_profile.ps1"
$PythonPath = Resolve-ProjectPython

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
