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

    Set-Location $ProjectRoot
    & $PythonPath daemon_main.py --mode $Mode --loop-seconds $LoopSeconds
}
finally {
    Clear-ProjectEmailSecret -PasswordPtr $PasswordPtr
}
