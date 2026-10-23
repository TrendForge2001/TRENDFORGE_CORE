# Run the existing webapp and paper engine on this PC. No remote disk mount.
[CmdletBinding()]
param(
    [string]$DataRoot = (Join-Path $env:LOCALAPPDATA 'TrendForgeCore'),
    [ValidateRange(1024,65535)][int]$Port = 10000
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
$venv = Join-Path $DataRoot 'python-env'
$python = Join-Path $venv 'Scripts\python.exe'
$requirements = Join-Path $repo 'requirements-pc.lock'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'Install Python 3.12 for Windows with the Python launcher, then run this script again.'
    }
    & py -3.12 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 environment creation failed.' }
}
Push-Location $repo
try {
    $stamp = Join-Path $venv 'trendforge-requirements.sha256'
    $digest = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    $saved = if (Test-Path -LiteralPath $stamp) { (Get-Content -LiteralPath $stamp -Raw).Trim() } else { '' }
    if ($saved -ne $digest) {
        & $python -m pip install -r $requirements
        if ($LASTEXITCODE -ne 0) { throw 'PC dependency installation failed.' }
        & $python -m pip check
        if ($LASTEXITCODE -ne 0) { throw 'PC dependency consistency check failed.' }
        Set-Content -LiteralPath $stamp -Value $digest -Encoding ASCII
    }
    & $python -m scripts.pc_paper_runtime --data-dir $DataRoot --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'PC paper runtime did not start; the storage guard remains active.' }
} finally { Pop-Location }
