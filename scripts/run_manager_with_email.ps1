param(
    [ValidateSet("local", "online", "ai")]
    [string]$Mode = "local",
    [switch]$SkipLocalPaper,
    [switch]$SkipResearch,
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
    if ($PasswordPtr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($PasswordPtr)
    }
    Remove-Item Env:\SMTP_PASSWORD -ErrorAction SilentlyContinue
}
