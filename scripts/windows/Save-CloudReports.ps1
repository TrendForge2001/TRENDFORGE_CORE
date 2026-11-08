# Preserve existing Render research reports before a deployment or restart.
# Requires only Windows PowerShell. Makes GET requests; never starts research or orders.
[CmdletBinding()]
param([string]$DataRoot = (Join-Path $env:LOCALAPPDATA 'TrendForgeCore'))
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$baseUrl = 'https://trendforge-core.onrender.com'
$archiveRoot = Join-Path ([IO.Path]::GetFullPath($DataRoot)) 'reports\research'
$secure = Read-Host 'Cloud Admin API Key (hidden; do not paste it into chat)' -AsSecureString
$credential = New-Object System.Management.Automation.PSCredential('report-backup', $secure)
$headers = @{ 'X-TrendForge-Admin-Key' = $credential.GetNetworkCredential().Password; 'Accept' = 'application/json' }
$utf8 = New-Object System.Text.UTF8Encoding($false)
$hasher = [Security.Cryptography.SHA256]::Create()
function Get-Digest([byte[]]$Bytes) {
    return ([BitConverter]::ToString($hasher.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
}
$saved = 0
$unfinished = 0
$offset = 0
try {
    New-Item -ItemType Directory -Force -Path $archiveRoot | Out-Null
    do {
        $list = Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/reports/batches?limit=100&offset=$offset" -Headers $headers -MaximumRedirection 0 -TimeoutSec 30
        $page = $list.Content | ConvertFrom-Json
        if ($null -eq $page.batches) { throw 'Invalid report history response.' }
        foreach ($item in $page.batches) {
            if ($item.status -ne 'completed') { $unfinished++; continue }
            $batchId = [string]$item.batch_id
            if ($batchId -notmatch '^[A-Za-z0-9_.:-]{1,120}$' -or $batchId.Contains('..')) { throw 'Invalid report identifier.' }
            $target = Join-Path $archiveRoot (Get-Digest ($utf8.GetBytes($batchId)))
            if (Test-Path -LiteralPath (Join-Path $target 'batch.json')) { continue }
            $response = Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/reports/batches/$batchId" -Headers $headers -MaximumRedirection 0 -TimeoutSec 30
            if ($response.Content.Length -gt 67108864) { throw 'Report backup is too large.' }
            $batch = $response.Content | ConvertFrom-Json
            if ($batch.status -ne 'completed' -or $batch.report.run_id -ne $batchId) { throw 'Report has not completed.' }
            [byte[]]$csv = @([byte]239, [byte]187, [byte]191) + $utf8.GetBytes([string]$batch.report.csv)
            if ((Get-Digest $csv) -ne $batch.report.sha256) { throw 'CSV checksum does not match.' }
            $staging = Join-Path $archiveRoot ('.partial-' + [Guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Path $staging | Out-Null
            try {
                [IO.File]::WriteAllBytes((Join-Path $staging 'report.csv'), $csv)
                if ($null -ne $batch.report.PSObject.Properties['xlsx_base64'] -and $batch.report.xlsx_base64) {
                    $excel = [Convert]::FromBase64String($batch.report.xlsx_base64)
                    if ((Get-Digest $excel) -ne $batch.report.xlsx_sha256) { throw 'Excel checksum does not match.' }
                    [IO.File]::WriteAllBytes((Join-Path $staging 'report.xlsx'), $excel)
                }
                [IO.File]::WriteAllText((Join-Path $staging 'batch.json'), $response.Content, $utf8)
                Move-Item -LiteralPath $staging -Destination $target
                $saved++
            } finally {
                if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
            }
        }
        $offset += 100
    } while ($page.batches.Count -eq 100)
    Write-Host "Saved $saved completed reports. Unfinished batches: $unfinished."
    Write-Host "PC report folder: $archiveRoot"
} catch {
    Write-Host 'Backup did not complete. Existing saved files were retained. Check the admin key, connection and free disk space.'
    exit 1
} finally {
    $headers.Clear()
    $secure.Dispose()
    $hasher.Dispose()
}
