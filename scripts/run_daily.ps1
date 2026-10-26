# 每天定时运行一次，生成当天的影视故事梗概
# 计划任务调用本脚本；也可手动执行：powershell -ExecutionPolicy Bypass -File .\scripts\run_daily.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

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
    throw '找不到 Python，请先安装 Python 3.10+'
}

$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$stamp = Get-Date -Format 'yyyy-MM-dd'
$outLog = Join-Path $logDir "run_$stamp.out.log"

Write-Output "[$(Get-Date -Format 'HH:mm:ss')] 开始生成影视故事梗概"
& $python (Join-Path $root 'run.py') @args 2>&1 | Tee-Object -FilePath $outLog -Append
$code = $LASTEXITCODE
Write-Output "[$(Get-Date -Format 'HH:mm:ss')] 结束，退出码 $code"
exit $code
