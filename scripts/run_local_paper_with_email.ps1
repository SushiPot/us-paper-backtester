param(
    [switch]$UseAdaptiveProfile,
    [switch]$ForceAdaptiveProfile,
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

    $ArgsList = @("local_paper_main.py", "--once")
    if ($UseAdaptiveProfile) {
        $ArgsList += "--use-adaptive-profile"
    }
    if ($ForceAdaptiveProfile) {
        $ArgsList += "--force-adaptive-profile"
    }

    Set-Location $ProjectRoot
    & $PythonPath @ArgsList
}
finally {
    Clear-ProjectEmailSecret -PasswordPtr $PasswordPtr
}
