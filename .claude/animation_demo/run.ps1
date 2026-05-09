#!/usr/bin/env pwsh
# Launch the animation demo using the project's local virtualenv.

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $here '..\..\.venv\Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    Write-Host "Project venv not found at: $venvPython" -ForegroundColor Red
    Write-Host "Falling back to system 'python'." -ForegroundColor Yellow
    & python (Join-Path $here 'demo.py')
} else {
    & $venvPython (Join-Path $here 'demo.py')
}
