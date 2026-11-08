# Copy existing cloud reports to the PC. Never changes paper positions.
[CmdletBinding()]
param(
    [string]$DataRoot = (Join-Path $env:LOCALAPPDATA 'TrendForgeCore'),
    [switch]$Watch,
    [string[]]$Files
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $DataRoot 'python-env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Start Start-TrendForgePaper.ps1 once to install the PC runtime, then run this backup command.'
}
$arguments = @('-m', 'scripts.save_research_reports', '--data-dir', $DataRoot)
if ($Watch) { $arguments += '--watch' }
foreach ($file in $Files) { $arguments += @('--file', $file) }
Push-Location $repo
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Report backup did not complete; existing report files were retained.' }
} finally { Pop-Location }
