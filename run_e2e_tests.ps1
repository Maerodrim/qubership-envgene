$ErrorActionPreference = "Stop"

# Navigate to project root
Set-Location -Path $PSScriptRoot

Write-Host "Running EnvGene Integration Tests..." -ForegroundColor Cyan

# Set PYTHONPATH so the tests can import the project modules
$env:PYTHONPATH = $PSScriptRoot

# Use the virtual environment python if it exists
$PythonExe = "python"
if (Test-Path ".venv\Scripts\pytest.exe") {
    $PytestExe = ".venv\Scripts\pytest.exe"
} else {
    $PytestExe = "pytest"
}

# Run pytest
& $PytestExe

if ($LASTEXITCODE -ne 0) {
    Write-Host "Tests failed!" -ForegroundColor Red
    exit $LASTEXITCODE
} else {
    Write-Host "All tests passed successfully." -ForegroundColor Green
}
