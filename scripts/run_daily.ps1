# 每天定时运行一次，生成当天的影视故事梗概
# 计划任务调用本脚本；也可手动执行：powershell -ExecutionPolicy Bypass -File .\scripts\run_daily.ps1

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

# 统一用 UTF-8 输出，避免中文日志乱码
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

# 优先用托管 Python，找不到就退回系统 Python
$pythonCandidates = @(
    'C:\Users\liqiao\.workbuddy-ai\binaries\python\versions\3.13.12\python.exe',
    'C:\Users\liqiao\AppData\Local\Programs\Python\Python313\python.exe'
)
$python = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    Write-Output '找不到 Python，请先安装 Python 3.10+'
    exit 2
}

$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$stamp = Get-Date -Format 'yyyy-MM-dd'
$outLog = Join-Path $logDir "run_$stamp.out.log"

Write-Output "[$(Get-Date -Format 'HH:mm:ss')] 开始生成影视故事梗概"

# 先把输出收进变量再写日志，这样 $LASTEXITCODE 才是 Python 的真实退出码
$output = & $python (Join-Path $root 'run.py') @args 2>&1
$code = $LASTEXITCODE

$lines = $output | ForEach-Object { $_.ToString() }
$lines | Out-File -FilePath $outLog -Append -Encoding utf8
$lines | ForEach-Object { Write-Output $_ }

Write-Output "[$(Get-Date -Format 'HH:mm:ss')] 结束，退出码 $code"
exit $code
