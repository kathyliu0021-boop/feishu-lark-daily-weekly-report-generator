# setup_windows.ps1
# One-click setup for Windows Scheduled Tasks
# Usage: powershell -ExecutionPolicy Bypass -File setup_windows.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = "$ScriptDir\feishu_report.py"

# Detect Python
$PythonExe = $null
foreach ($cmd in @("python", "py", "python3")) {
    try {
        $where = Get-Command $cmd -ErrorAction Stop
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $PythonExe = $where.Source
            break
        }
    } catch {}
}

if (-not $PythonExe) {
    Write-Host "Error: Python 3 not found. Please install Python 3.8+" -ForegroundColor Red
    exit 1
}
Write-Host "Using Python: $PythonExe" -ForegroundColor Green

# Check lark-cli
try {
    lark-cli --version | Out-Null
    Write-Host "lark-cli found" -ForegroundColor Green
} catch {
    Write-Host "Error: lark-cli not found. Run: npm install -g @larksuite/cli" -ForegroundColor Red
    exit 1
}

# Check config file
if (-not (Test-Path "$ScriptDir\config.json")) {
    Write-Host "Error: config.json not found. Copy config.example.json and fill in your settings first." -ForegroundColor Red
    exit 1
}

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Daily report: every day at 18:30
$DailyAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$PythonScript`" --mode daily" `
    -WorkingDirectory $ScriptDir
$DailyTrigger = New-ScheduledTaskTrigger -Daily -At "18:30"
$DailySettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable
Unregister-ScheduledTask -TaskName "FeishuDailyReport" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "FeishuDailyReport" -Action $DailyAction -Trigger $DailyTrigger `
    -Settings $DailySettings -Principal $Principal -Force | Out-Null
Write-Host "✅ Daily report scheduled (every day at 18:30)" -ForegroundColor Green

# Weekly report: every Sunday at 15:00
$WeeklyAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$PythonScript`" --mode weekly" `
    -WorkingDirectory $ScriptDir
$WeeklyTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Sunday -At "15:00"
$WeeklySettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable
Unregister-ScheduledTask -TaskName "FeishuWeeklyReport" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "FeishuWeeklyReport" -Action $WeeklyAction -Trigger $WeeklyTrigger `
    -Settings $WeeklySettings -Principal $Principal -Force | Out-Null
Write-Host "✅ Weekly report scheduled (every Sunday at 15:00)" -ForegroundColor Green

# Token refresh reminder: every Monday at 09:00
$ReminderMsg = "Lark/Feishu token is about to expire. Please run:`n`nlark-cli auth login --recommend"
$ReminderAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-Command `"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('$ReminderMsg', 'Token Refresh Reminder')`""
$ReminderTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Monday -At "09:00"
Unregister-ScheduledTask -TaskName "FeishuTokenReminder" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "FeishuTokenReminder" -Action $ReminderAction `
    -Trigger $ReminderTrigger -Principal $Principal -Force | Out-Null
Write-Host "✅ Token refresh reminder scheduled (every Monday at 09:00)" -ForegroundColor Green

Write-Host ""
Write-Host "🎉 Setup complete!" -ForegroundColor Cyan
Write-Host "Test daily report:  $PythonExe `"$PythonScript`" --mode daily"
Write-Host "Test weekly report: $PythonExe `"$PythonScript`" --mode weekly"
Write-Host ""
Write-Host "Note: tasks are registered under your user login session." -ForegroundColor Yellow
Write-Host "If the scheduled time passes while the machine is off, it will run on next available login (-StartWhenAvailable)." -ForegroundColor Yellow
