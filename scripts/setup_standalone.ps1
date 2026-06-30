$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Get-BasePython {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    foreach ($command in @(
        @{ File = "py"; Args = @("-3.12", "-c", "import sys; print(sys.executable)") },
        @{ File = "py"; Args = @("-3", "-c", "import sys; print(sys.executable)") },
        @{ File = "python"; Args = @("-c", "import sys; print(sys.executable)") }
    )) {
        try {
            $output = & $command.File @($command.Args) 2>$null
            if ($LASTEXITCODE -eq 0 -and $output) {
                $path = [string]$output[0]
                if ($path -and $path -notmatch "\\Microsoft\\WindowsApps\\python.exe" -and $path -notmatch "\\.cache\\codex-runtimes\\") {
                    return $path
                }
            }
        }
        catch {
        }
    }

    return ""
}

function Install-PythonWithWinget {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        return ""
    }

    Write-Host "[INFO] Python was not found. Trying winget install Python 3.12..."
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        return ""
    }

    return Get-BasePython
}

Set-Location $ProjectRoot

$BasePython = Get-BasePython
if (-not $BasePython) {
    $BasePython = Install-PythonWithWinget
}

if (-not $BasePython) {
    throw "No standalone Python installation was found. Install Python 3.12, then rerun setup_standalone.cmd."
}

Write-Host "[INFO] Base Python: $BasePython"

& $BasePython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.11 or newer is required."
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "[INFO] Creating .venv..."
    & $BasePython -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create .venv."
    }
}

Write-Host "[INFO] Project Python: $VenvPython"
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}

& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install requirements.txt."
}

& $VenvPython -m py_compile `
    (Join-Path $ProjectRoot "agents_main.py") `
    (Join-Path $ProjectRoot "local_paper_main.py") `
    (Join-Path $ProjectRoot "daemon_main.py") `
    (Join-Path $ProjectRoot "web_app.py")
if ($LASTEXITCODE -ne 0) {
    throw "Compile check failed."
}

Write-Host "[OK] Standalone runtime is ready."
