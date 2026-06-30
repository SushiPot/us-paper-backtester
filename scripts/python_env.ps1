function Resolve-ProjectPython {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

    if (Test-Path $VenvPython) {
        return $VenvPython
    }

    $SetupScript = Join-Path $PSScriptRoot "setup_standalone.ps1"
    & $SetupScript
    if ($LASTEXITCODE -ne 0) {
        throw "Standalone setup failed."
    }

    if (-not (Test-Path $VenvPython)) {
        throw "Project Python was not created: $VenvPython"
    }

    return $VenvPython
}
