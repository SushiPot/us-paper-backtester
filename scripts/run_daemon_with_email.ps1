param(
    [ValidateSet("local", "online", "ai")]
    [string]$Mode = "online",
    [string]$LoopSeconds = "900",
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

    Set-Location $ProjectRoot
    & $PythonPath daemon_main.py --mode $Mode --loop-seconds $LoopSeconds
}
finally {
    Clear-ProjectEmailSecret -PasswordPtr $PasswordPtr
}
