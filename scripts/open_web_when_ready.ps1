param(
    [string]$Url = "http://127.0.0.1:5000",
    [int]$TimeoutSeconds = 45
)

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            Start-Process $Url
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

exit 1
