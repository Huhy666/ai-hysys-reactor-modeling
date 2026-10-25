param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"
$sourceRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$targetRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd('\')
$targetPrefix = $targetRoot + [IO.Path]::DirectorySeparatorChar
$pythonPath = Join-Path $targetRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Target must be the configured workstation project with its own .venv."
}
if ($sourceRoot.TrimEnd('\') -eq $targetRoot) {
    throw "Run this updater from a separately extracted source package, not the target project."
}

$port = 8000
$envPath = Join-Path $targetRoot '.env'
if (Test-Path -LiteralPath $envPath) {
    foreach ($line in Get-Content -LiteralPath $envPath) {
        if ($line -match '^\s*APP_PORT\s*=\s*["'']?(\d+)') { $port = [int]$Matches[1] }
    }
}
$listeners = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties()
if ($listeners.GetActiveTcpListeners() | Where-Object { $_.Port -eq $port }) {
    throw "Port $port is still in use. Stop the web service with Ctrl+C before updating."
}

$items = @()
foreach ($directory in @('app', 'scripts')) {
    $folder = Join-Path $sourceRoot $directory
    foreach ($file in Get-ChildItem -LiteralPath $folder -File -Recurse) {
        if ($file.Extension -in @('.py', '.ps1', '.html', '.js', '.css')) { $items += $file }
    }
}
foreach ($name in @('pyproject.toml', '.env.example', 'start_web.cmd',
    'run_toluene_check.cmd', 'run_full_acceptance.cmd', 'run_deadline_acceptance.cmd',
    'run_generalization.cmd', 'inspect_conversion_case.cmd')) {
    $path = Join-Path $sourceRoot $name
    if (Test-Path -LiteralPath $path) { $items += Get-Item -LiteralPath $path }
}
if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot 'app\runtime.py'))) {
    throw "Source package is incomplete: app/runtime.py is missing."
}
$backup = Join-Path $targetRoot ('update-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss') +
    '-' + [guid]::NewGuid().ToString('N').Substring(0, 6))
$copied = 0
foreach ($file in $items) {
    $relative = $file.FullName.Substring($sourceRoot.Length).TrimStart('\', '/')
    $destination = [IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
    if (-not $destination.StartsWith($targetPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refused a path outside the target project."
    }
    if (Test-Path -LiteralPath $destination) {
        $saved = Join-Path $backup $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $saved) -Force | Out-Null
        Copy-Item -LiteralPath $destination -Destination $saved -Force
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
    $copied += 1
}
Write-Host "Updated $copied source files. Original source backup: $backup"
Write-Host "Preserved .env, .venv, runs and existing HYSYS case files."
Push-Location -LiteralPath $targetRoot
try {
    & $pythonPath scripts\check_runtime.py
    if ($LASTEXITCODE -ne 0) { throw "Source preflight failed. Preserve the output and backup." }
} finally { Pop-Location }
Write-Host "Start scripts\run_server.py in the TARGET project, then run:"
Write-Host ".venv\Scripts\python.exe scripts\check_runtime.py --url http://127.0.0.1:$port"
