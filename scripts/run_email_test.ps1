param(
    [string]$SmtpHost = "smtp.office365.com",
    [string]$SmtpPort = "587",
    [string]$SmtpUsername = "",
    [string]$EmailFrom = "",
    [string]$EmailTo = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonPath = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $PythonPath)) {
    throw "Bundled Python not found: $PythonPath"
}

if (-not $SmtpUsername) {
    $SmtpUsername = Read-Host "SMTP username / email"
}

if (-not $EmailFrom) {
    $EmailFrom = $SmtpUsername
}

if (-not $EmailTo) {
    $EmailTo = Read-Host "Recipient email"
}

$SecurePassword = Read-Host "SMTP password or app password" -AsSecureString
$PasswordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)

try {
    $PlainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($PasswordPtr)

    $env:EMAIL_ENABLED = "true"
    $env:SMTP_HOST = $SmtpHost
    $env:SMTP_PORT = $SmtpPort
    $env:SMTP_USERNAME = $SmtpUsername
    $env:SMTP_PASSWORD = $PlainPassword
    $env:EMAIL_FROM = $EmailFrom
    $env:EMAIL_TO = $EmailTo
    $env:SMTP_USE_TLS = "true"

    Set-Location $ProjectRoot
    & $PythonPath email_test_main.py --send
}
finally {
    if ($PasswordPtr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($PasswordPtr)
    }
    Remove-Item Env:\SMTP_PASSWORD -ErrorAction SilentlyContinue
}
