param([int]$Port = 5000)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Run scripts/setup.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) { throw 'Run npm ci and npm run build in frontend first.' }
$env:CARETRACE_PORT = "$Port"
$env:PYTHONUTF8 = '1'
Write-Host "CareTrace: http://127.0.0.1:$Port (Ctrl+C to stop)"
& $projectPython -m caretrace.app
