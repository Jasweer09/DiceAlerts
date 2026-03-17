## Dice Job Monitor - Windows Task Scheduler Setup
## Run as: powershell -ExecutionPolicy Bypass -File deploy\setup_windows_task.ps1

$taskName = "DiceJobMonitor"
$batPath = Join-Path $PSScriptRoot "..\run_monitor.bat"
$workDir = Split-Path $batPath -Parent

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "[OK] Removed existing task"
}

# Create action — use wscript + VBS wrapper to run without visible window
$vbsPath = Join-Path $PSScriptRoot "..\run_hidden.vbs"
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$vbsPath`"" `
    -WorkingDirectory $workDir

# Create trigger: repeat every 5 minutes indefinitely
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 9999)

# Settings: run on battery, don't stop on battery, start if missed
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

# Register the task
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Force

Write-Host ""
Write-Host "============================================================"
Write-Host "  Dice Job Monitor - Task Scheduled"
Write-Host "============================================================"
Write-Host "  Task Name  : $taskName"
Write-Host "  Interval   : Every 5 minutes"
Write-Host "  Script     : $batPath"
Write-Host "  Log file   : $workDir\monitor_output.log"
Write-Host "============================================================"
Write-Host ""
Write-Host "Commands:"
Write-Host "  Check status : Get-ScheduledTask -TaskName '$taskName' | Get-ScheduledTaskInfo"
Write-Host "  Run now      : Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  Stop         : Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
Write-Host "  View logs    : Get-Content '$workDir\monitor_output.log' -Tail 50"
Write-Host ""

# Trigger first run
Start-ScheduledTask -TaskName $taskName
Write-Host "[OK] First run triggered. Check monitor_output.log for results."
