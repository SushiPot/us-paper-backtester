function Initialize-ProjectEmailEnvironment {
    param(
        [string]$SmtpHost = "smtp.qq.com",
        [string]$SmtpPort = "587",
        [string]$SmtpUsername = "",
        [string]$EmailFrom = "",
        [string]$EmailTo = ""
    )

    $ProfileDir = Join-Path $env:APPDATA "us_paper_backtester"
    $ProfilePath = Join-Path $ProfileDir "email_profile.json"
    $CredentialPath = Join-Path $ProfileDir "qq_mail_credential.xml"
    $SavedProfile = $null
    $SecurePassword = $null
    $NeedsProfileSave = -not (Test-Path $ProfilePath)
    $NeedsCredentialSave = -not (Test-Path $CredentialPath)

    if (Test-Path $ProfilePath) {
        try {
            $SavedProfile = Get-Content -Raw -Encoding UTF8 $ProfilePath | ConvertFrom-Json
            Write-Host "[INFO] Loaded saved email profile: $ProfilePath"
        }
        catch {
            Write-Host "[WARN] Failed to read saved email profile: $($_.Exception.Message)"
        }
    }

    if ($SavedProfile) {
        if ($SavedProfile.smtp_host -and $SmtpHost -eq "smtp.qq.com") {
            $SmtpHost = [string]$SavedProfile.smtp_host
        }
        if ($SavedProfile.smtp_port -and $SmtpPort -eq "587") {
            $SmtpPort = [string]$SavedProfile.smtp_port
        }
        if (-not $SmtpUsername -and $SavedProfile.smtp_username) {
            $SmtpUsername = [string]$SavedProfile.smtp_username
        }
        if (-not $EmailFrom -and $SavedProfile.email_from) {
            $EmailFrom = [string]$SavedProfile.email_from
        }
        if (-not $EmailTo -and $SavedProfile.email_to) {
            $EmailTo = [string]$SavedProfile.email_to
        }
    }

    if (Test-Path $CredentialPath) {
        try {
            $Credential = Import-Clixml -Path $CredentialPath
            if (-not $SmtpUsername) {
                $SmtpUsername = $Credential.UserName
            }
            if ($Credential.UserName -eq $SmtpUsername) {
                $SecurePassword = $Credential.Password
                Write-Host "[INFO] Loaded encrypted QQ Mail authorization code."
            }
            else {
                Write-Host "[WARN] Saved credential user does not match SMTP username; please enter authorization code again."
                $NeedsCredentialSave = $true
            }
        }
        catch {
            Write-Host "[WARN] Failed to load saved QQ Mail credential: $($_.Exception.Message)"
            $NeedsCredentialSave = $true
        }
    }

    if (-not $SmtpUsername) {
        $SmtpUsername = Read-Host "QQ email address / SMTP username"
    }

    if (-not $EmailFrom) {
        $EmailFrom = $SmtpUsername
    }

    if (-not $EmailTo) {
        $EmailTo = Read-Host "Recipient email"
        $NeedsProfileSave = $true
    }

    if (-not $SecurePassword) {
        Write-Host "[INFO] QQ Mail uses an authorization code here, not your QQ login password."
        $SecurePassword = Read-Host "QQ Mail authorization code" -AsSecureString
        $NeedsCredentialSave = $true
    }

    if ($NeedsProfileSave -or $NeedsCredentialSave) {
        $SaveAnswer = Read-Host "Save QQ Mail profile encrypted for future runs? (Y/n)"
        if ($SaveAnswer.Trim().ToLower() -ne "n") {
            New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
            [pscustomobject]@{
                smtp_host = $SmtpHost
                smtp_port = $SmtpPort
                smtp_username = $SmtpUsername
                email_from = $EmailFrom
                email_to = $EmailTo
            } | ConvertTo-Json | Set-Content -Encoding UTF8 -Path $ProfilePath

            $CredentialToSave = [System.Management.Automation.PSCredential]::new($SmtpUsername, $SecurePassword)
            $CredentialToSave | Export-Clixml -Path $CredentialPath
            Write-Host "[OK] Saved encrypted email profile to: $ProfileDir"
        }
    }

    $PasswordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
    $PlainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($PasswordPtr)

    $env:EMAIL_ENABLED = "true"
    $env:SMTP_HOST = $SmtpHost
    $env:SMTP_PORT = $SmtpPort
    $env:SMTP_USERNAME = $SmtpUsername
    $env:SMTP_PASSWORD = $PlainPassword
    $env:EMAIL_FROM = $EmailFrom
    $env:EMAIL_TO = $EmailTo
    $env:SMTP_USE_TLS = "true"

    return $PasswordPtr
}

function Clear-ProjectEmailSecret {
    param([IntPtr]$PasswordPtr)

    if ($PasswordPtr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($PasswordPtr)
    }
    Remove-Item Env:\SMTP_PASSWORD -ErrorAction SilentlyContinue
}

function Remove-ProjectEmailProfile {
    $ProfileDir = Join-Path $env:APPDATA "us_paper_backtester"
    $ProfilePath = Join-Path $ProfileDir "email_profile.json"
    $CredentialPath = Join-Path $ProfileDir "qq_mail_credential.xml"

    Remove-Item -LiteralPath $ProfilePath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $CredentialPath -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Removed saved QQ Mail profile from: $ProfileDir"
}
