$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment missing. Run .\setup.ps1 first."
}

& $Python (Join-Path $Root "radar.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Report = Join-Path $Root "reports\latest.html"
if (Test-Path $Report) { Start-Process $Report }
