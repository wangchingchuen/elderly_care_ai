param([switch]$Cuda128, [string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
& $Python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed. Use Python 3.10 or 3.11.' }
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
& $projectPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed' }
if ($Cuda128) {
    & $projectPython -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
} else {
    & $projectPython -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
}
if ($LASTEXITCODE -ne 0) { throw 'PyTorch install failed' }
& $projectPython -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed' }
Push-Location frontend
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
Write-Host 'CareTrace is ready. Run .\scripts\start.ps1'
