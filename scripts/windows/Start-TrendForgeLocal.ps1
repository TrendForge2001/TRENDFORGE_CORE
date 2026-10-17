# R70.2 observation-only launcher. Must run from a signed-in Windows user session.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
$env:TRENDFORGE_DATA_DIR = [Environment]::GetEnvironmentVariable('TRENDFORGE_DATA_DIR', 'User')
$env:DATABASE_PATH = [Environment]::GetEnvironmentVariable('DATABASE_PATH', 'User')
if (-not $env:TRENDFORGE_DATA_DIR -or -not $env:DATABASE_PATH) {
    throw 'User environment missing; run Set-TrendForgeEnvironment.ps1 -Apply'
}
Push-Location $repo
try {
    & $python -m scripts.local_engine_runtime preflight
    if ($LASTEXITCODE -ne 0) { throw 'Local runtime blocked by preflight' }
    & $python -m scripts.local_engine_runtime run --interval 60
    if ($LASTEXITCODE -ne 0) { throw 'Local runtime returned failure' }
} finally { Pop-Location }
