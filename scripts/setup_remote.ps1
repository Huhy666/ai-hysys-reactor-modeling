$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot

try {
    $created = $false
    if (Test-Path -LiteralPath ".venv\Scripts\python.exe") {
        & .\.venv\Scripts\python.exe -c "import platform,sys; assert sys.version_info[:2] in [(3,11),(3,12)]; assert platform.architecture()[0] == '64bit'"
        if ($LASTEXITCODE -ne 0) { throw "Existing virtual environment is incompatible. Preserve it and use a new project directory." }
        $created = $true
    }
    if (-not $created -and (Get-Command py -ErrorAction SilentlyContinue)) {
        foreach ($version in @("3.12", "3.11")) {
            & py "-$version" -c "import platform; assert platform.architecture()[0] == '64bit'" 2>$null
            if ($LASTEXITCODE -eq 0) {
                & py "-$version" -m venv .venv
                if ($LASTEXITCODE -ne 0) { throw "Could not create virtual environment." }
                $created = $true
                break
            }
        }
    }

    if (-not $created -and (Get-Command python -ErrorAction SilentlyContinue)) {
        & python -c "import platform,sys; assert sys.version_info[:2] in [(3,11),(3,12)]; assert platform.architecture()[0] == '64bit'"
        if ($LASTEXITCODE -ne 0) { throw "64-bit Python 3.11 or 3.12 is required." }
        & python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create virtual environment." }
        $created = $true
    }

    if (-not $created) {
        throw "64-bit Python 3.11 or 3.12 was not found."
    }

    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip update failed." }
    & .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { throw "Project dependency installation failed." }

    if (-not (Test-Path -LiteralPath ".env")) {
        Copy-Item -LiteralPath ".env.example" -Destination ".env"
        Write-Host "Created .env from .env.example. Fill environment-specific values before running."
    }

    Write-Host "Setup complete. Run: .\.venv\Scripts\python.exe scripts\run_server.py"
}
finally {
    Pop-Location
}
