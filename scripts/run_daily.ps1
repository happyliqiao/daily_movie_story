# 每天定时运行：云端（GitHub Actions）为主，本机为兜底
# 计划任务调用本脚本；也可手动执行：powershell -ExecutionPolicy Bypass -File .\scripts\run_daily.ps1
#
# 逻辑：
#   1. 拉取仓库最新内容（云端生成的梗概会提交回仓库）
#   2. 把仓库里的结果同步到本地 E 盘目录
#   3. 云端今天已经生成过 -> 直接跳过（避免重复发邮件）
#   4. 云端没生成（失败/未跑）-> 本机生成、发邮件，并提交回仓库

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

# ---------- 读取本地输出目录（.env 里的 MOVIE_OUTPUT_DIR）----------
$envFile = Join-Path $root '.env'
$localOut = $null
if (Test-Path $envFile) {
    $line = Get-Content $envFile -Encoding UTF8 |
            Where-Object { $_ -match '^\s*MOVIE_OUTPUT_DIR\s*=' } |
            Select-Object -First 1
    if ($line) { $localOut = ($line -split '=', 2)[1].Trim() }
}
if (-not $localOut) { $localOut = Join-Path $root 'output' }
$repoOut = Join-Path $root 'output'

# ---------- 找 Python ----------
$pythonCandidates = @(
    'C:\Users\liqiao\.workbuddy-ai\binaries\python\versions\3.13.12\python.exe',
    'C:\Users\liqiao\AppData\Local\Programs\Python\Python313\python.exe'
)
$python = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) { $python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python) {
    Write-Output '找不到 Python，请先安装 Python 3.10+'
    exit 2
}

$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$stamp = Get-Date -Format 'yyyy-MM-dd'
$outLog = Join-Path $logDir "run_$stamp.out.log"

function Write-RunLog([string]$text) {
    Write-Output $text
    Add-Content -Path $outLog -Value $text -Encoding utf8
}

function Sync-RepoToLocal {
    if (-not (Test-Path $repoOut)) { return }
    if (-not (Test-Path $localOut)) { New-Item -ItemType Directory -Path $localOut -Force | Out-Null }
    $files = Get-ChildItem -Path $repoOut -File -ErrorAction SilentlyContinue |
             Where-Object { $_.Extension -in '.md', '.html' }
    $n = 0
    foreach ($f in $files) {
        $dest = Join-Path $localOut $f.Name
        if (-not (Test-Path $dest) -or (Get-Item $dest).LastWriteTime -lt $f.LastWriteTime) {
            Copy-Item $f.FullName $dest -Force
            $n++
        }
    }
    if ($n -gt 0) { Write-RunLog "已同步 $n 个文件到本地：$localOut" }
}

Write-RunLog "[$(Get-Date -Format 'HH:mm:ss')] 开始检查"

# ---------- 1. 拉取云端结果 ----------
& git -C $root pull --rebase origin master 2>&1 | Out-Null
Write-RunLog "[$(Get-Date -Format 'HH:mm:ss')] 已同步仓库最新内容"

# ---------- 2. 同步到本地目录 ----------
Sync-RepoToLocal

# ---------- 3. 云端今天是否已经生成过 ----------
$today = (Get-Date).ToString('yyyy-MM-dd')
$cloudDone = @(Get-ChildItem -Path $repoOut -Filter "$today`_*.md" -ErrorAction SilentlyContinue)
if ($cloudDone.Count -gt 0) {
    Write-RunLog "云端今天已生成（$($cloudDone[0].Name)），跳过本机生成，避免重复发邮件"
    exit 0
}

# ---------- 4. 本机兜底生成 ----------
Write-RunLog "[$(Get-Date -Format 'HH:mm:ss')] 云端未生成，本机兜底开始"
$env:MOVIE_OUTPUT_DIR = $repoOut

$output = & $python (Join-Path $root 'run.py') @args 2>&1
$code = $LASTEXITCODE
$lines = $output | ForEach-Object { $_.ToString() }
$lines | Out-File -FilePath $outLog -Append -Encoding utf8
$lines | ForEach-Object { Write-Output $_ }

Sync-RepoToLocal

# ---------- 5. 提交回仓库，让云端知道今天的进度 ----------
if ($code -eq 0) {
    & git -C $root config user.name 'happyliqiao'
    & git -C $root config user.email 'happyliqiao@users.noreply.github.com'
    & git -C $root add -A output data/state.json 2>&1 | Out-Null
    & git -C $root diff --staged --quiet
    if ($LASTEXITCODE -ne 0) {
        & git -C $root commit -q -m "chore: 本机兜底生成 $today 的影视故事梗概"
        & git -C $root push -q origin master 2>&1 | Out-Null
        Write-RunLog "[$(Get-Date -Format 'HH:mm:ss')] 结果已提交回仓库"
    }
}

Write-RunLog "[$(Get-Date -Format 'HH:mm:ss')] 结束，退出码 $code"
exit $code
