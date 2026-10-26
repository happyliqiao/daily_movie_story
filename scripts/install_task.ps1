# 注册/更新 Windows 计划任务：每天固定时间自动生成影视故事梗概
# 用法：powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1
#       powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1 -Time 08:30

param(
    [string]$Time = '09:30',
    [string]$TaskName = '每日影视故事梗概'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runner = Join-Path $root 'scripts\run_daily.ps1'

if (-not (Test-Path $runner)) { throw "找不到运行脚本：$runner" }

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`"" `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $Time

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "已删除旧任务：$TaskName"
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description '每天自动生成一篇电影/电视剧的分段故事梗概（每 10 分钟一段）' | Out-Null

Write-Output "已创建计划任务：$TaskName"
Write-Output "  执行时间：每天 $Time"
Write-Output "  运行脚本：$runner"
Write-Output ""
Write-Output "立即试跑一次：Start-ScheduledTask -TaskName '$TaskName'"
Write-Output "查看状态：Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Output "删除任务：Unregister-ScheduledTask -TaskName '$TaskName'"
