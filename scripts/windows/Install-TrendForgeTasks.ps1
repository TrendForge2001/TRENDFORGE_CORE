# R70.2 scheduled observer, requires explicit -Action Install. No order execution.
[CmdletBinding()]
param([ValidateSet('Status','Install','Remove')][string]$Action = 'Status')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$startTask = 'TrendForge R70.2 Start'
$stopTask = 'TrendForge R70.2 Stop'
$startScript = Join-Path $PSScriptRoot 'Start-TrendForgeLocal.ps1'
$stopScript = Join-Path $PSScriptRoot 'Stop-TrendForgeLocal.ps1'
if ($Action -eq 'Status') {
    Get-ScheduledTask -TaskName $startTask,$stopTask -ErrorAction SilentlyContinue |
        Select-Object TaskName, State
    return
}
if ($Action -eq 'Remove') {
    foreach ($name in @($startTask, $stopTask)) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    }
    Write-Host 'TrendForge R70.2 scheduled tasks removed.'
    return
}
if ((Get-TimeZone).Id -ne 'India Standard Time') {
    throw 'PC timezone is not India Standard Time. Correct Windows timezone before installing tasks.'
}
if (-not ([Environment]::GetEnvironmentVariable('DATABASE_PATH','User'))) {
    throw 'Configure the user-level database path before installing tasks.'
}
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 9)
$weekday = @('Monday','Tuesday','Wednesday','Thursday','Friday')
foreach ($task in @(
    @{ Name=$startTask; Script=$startScript; Time='08:45' },
    @{ Name=$stopTask; Script=$stopScript; Time='16:00' }
)) {
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $task.Script + '"'
    $taskAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekday -At $task.Time
    Register-ScheduledTask -TaskName $task.Name -Action $taskAction -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
}
Write-Host 'R70.2 OBSERVER TASKS INSTALLED (08:45 start / 16:00 stop Windows local time).'
Write-Host 'Requires a signed-in Windows session and PC powered on. No trading or scanning enabled.'
