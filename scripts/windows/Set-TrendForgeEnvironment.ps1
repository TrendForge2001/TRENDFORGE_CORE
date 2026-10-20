# R70.2. Save user-level settings only after read-only schema verification.
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$DataRoot = 'C:\TrendForgeData'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
$db = Join-Path $DataRoot 'database\trendforge.db'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'TrendForge Python virtual environment is missing.'
}
if (-not (Test-Path -LiteralPath $db -PathType Leaf)) {
    throw "Database missing: $db. Configuration was not changed."
}
Push-Location $repo
try {
    & $python -m scripts.local_engine_runtime preflight --root $DataRoot --db $db
    if ($LASTEXITCODE -ne 0) { throw 'Database schema/preflight failed. Configuration was not changed.' }
} finally { Pop-Location }

if (-not $Apply) {
    Write-Host 'READ-ONLY CHECK PASSED. Run with -Apply to save user environment variables.'
    return
}
foreach ($entry in @(@('TRENDFORGE_DATA_DIR',$DataRoot), @('DATABASE_PATH',$db))) {
    $existing = [Environment]::GetEnvironmentVariable($entry[0], 'User')
    if ($existing -and ($existing -ne $entry[1])) {
        throw "Existing user variable $($entry[0]) differs. Review it before overwriting."
    }
}
[Environment]::SetEnvironmentVariable('TRENDFORGE_DATA_DIR', $DataRoot, 'User')
[Environment]::SetEnvironmentVariable('DATABASE_PATH', $db, 'User')
$env:TRENDFORGE_DATA_DIR = $DataRoot
$env:DATABASE_PATH = $db
if ([Environment]::GetEnvironmentVariable('DATABASE_PATH','User') -ne $db) {
    throw 'Unable to verify saved DATABASE_PATH'
}
Write-Host 'R70.2 USER ENVIRONMENT SAVED. Open a new PowerShell session to verify.'
