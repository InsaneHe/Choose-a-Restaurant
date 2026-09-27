$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing .venv. Create it and install requirements-build.txt first."
}

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean ChooseRestaurant.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }
    Write-Output "Built: $projectRoot\dist\ChooseRestaurant\ChooseRestaurant.exe"
}
finally {
    Pop-Location
}
