<#
  CodeMentor 一键启动（Windows / PowerShell 5.1 及以上）

  做四件事：
    1. 没有虚拟环境就建一个（有 uv 用 uv，没有就用 python -m venv）
    2. 依赖没装、或 requirements.txt 改过，就装一遍（默认源失败自动换清华镜像）
    3. 找一个空闲端口起后端（默认 8000，被占用自动往后找）
    4. 等 /api/health 通了，自动打开浏览器

  用法：
    双击根目录的 start.bat
    或：powershell -ExecutionPolicy Bypass -File scripts\start.ps1
    换端口：start.bat -Port 8100        不自动开浏览器：-NoBrowser
    强制重装依赖：-Reinstall
    网络慢/装依赖卡住：-Mirror（一开始就走清华镜像）

  关掉窗口 = 停止服务。
#>
param(
    [int]$Port = 8000,
    [switch]$NoBrowser,
    [switch]$Reinstall,
    [switch]$Mirror
)

$ErrorActionPreference = 'Stop'

function Say-Info { param($msg) Write-Host "  $msg" -ForegroundColor Gray }
function Say-Ok { param($msg) Write-Host "  √ $msg" -ForegroundColor Green }
function Say-Warn { param($msg) Write-Host "  ! $msg" -ForegroundColor Yellow }
function Say-Fail { param($msg) Write-Host "  × $msg" -ForegroundColor Red }

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$venv = Join-Path $backend '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
$reqFile = Join-Path $backend 'requirements.txt'
$marker = Join-Path $venv '.deps-hash'

Write-Host ''
Write-Host '  CodeMentor · 编程学习助手' -ForegroundColor Cyan
Write-Host '  ------------------------------------------------'

if (-not (Test-Path $backend)) {
    Say-Fail "没找到 backend 目录，请在项目根目录运行（或双击 start.bat）"
    exit 1
}

# ---------------------------------------------------------------- 0) 已经在跑？
# 目标端口上如果已经跑着本程序，就别起第二个：
# Qdrant 本地 embedded 库同一时间只允许一个实例打开，起两个会互相锁死（RAG 直接降级）
function Test-OurApp {
    param([int]$p)
    try {
        $resp = Invoke-WebRequest -Uri ("http://127.0.0.1:" + $p + "/api/health") -TimeoutSec 3 -UseBasicParsing
        if ($resp.StatusCode -ne 200) { return $false }
        $body = $resp.Content | ConvertFrom-Json
        return ([string]$body.app -like '*CodeMentor*')
    }
    catch { return $false }
}

if (Test-OurApp $Port) {
    $aliveUrl = 'http://127.0.0.1:' + $Port
    Say-Ok "服务已经在运行：$aliveUrl"
    Say-Info '没有重复启动（Qdrant 本地库同一时间只能一个实例用）'
    if (-not $NoBrowser) {
        try { Start-Process $aliveUrl; Say-Ok '已尝试在浏览器打开' } catch { }
    }
    exit 0
}

# ---------------------------------------------------------------- 1) Python 环境
if (-not (Test-Path $venvPython)) {
    Say-Info '首次运行：正在创建 Python 虚拟环境…'
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        Push-Location $backend
        & $uv.Source venv --python 3.12 .venv
        Pop-Location
    }
    else {
        $sys = Get-Command python -ErrorAction SilentlyContinue
        if (-not $sys) { $sys = Get-Command py -ErrorAction SilentlyContinue }
        if (-not $sys) {
            Say-Fail '没找到 Python。请先安装 Python 3.10+（安装时勾选 Add Python to PATH）'
            Say-Info '下载地址：https://www.python.org/downloads/'
            exit 1
        }
        Push-Location $backend
        & $sys.Source -m venv .venv
        Pop-Location
    }
}
if (-not (Test-Path $venvPython)) {
    Say-Fail '虚拟环境创建失败，请手动执行：cd backend && python -m venv .venv'
    exit 1
}
Say-Ok 'Python 环境就绪'

# ---------------------------------------------------------------- 2) 依赖
# 说明：调用原生 exe 并把 stderr 重定向到别的流（*> / 2>&1）时，
# PowerShell 会把 stderr 当成 ErrorRecord；脚本顶层设了 ErrorActionPreference='Stop'，
# 于是「包没装」这种正常情况也会被当成致命错误抛出。所以下面几处临时改成 Continue。
$eap = $ErrorActionPreference

$needDeps = $true
if (-not $Reinstall) {
    if ((Test-Path $marker) -and (Test-Path $reqFile)) {
        $saved = (Get-Content $marker -Raw).Trim()
        $now = (Get-FileHash $reqFile -Algorithm SHA256).Hash
        if ($saved -eq $now) { $needDeps = $false; Say-Ok '依赖已就绪（requirements.txt 没变）' }
    }
    if ($needDeps) {
        # 没有标记文件也别急着装：先看这些包能不能 import
        # （uv 建的 venv 根本没有 pip，直接 pip install 会报 "No module named pip"）
        $ErrorActionPreference = 'Continue'
        & $venvPython -c "import fastapi, uvicorn, sqlalchemy, langgraph, qdrant_client" *> $null
        $importOk = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $eap
        if ($importOk) {
            try { (Get-FileHash $reqFile -Algorithm SHA256).Hash | Set-Content $marker -Encoding ASCII } catch { }
            $needDeps = $false
            Say-Ok '依赖已就绪（环境里已经装好了）'
        }
    }
}
if ($needDeps) {
    Say-Info '安装后端依赖（首次需要几分钟，请耐心等）…'
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    $mirror = 'https://pypi.tuna.tsinghua.edu.cn/simple'
    $installed = $false
    # 下载卡住时别无限等：uv 的 HTTP 超时压到 30s，pip 给超时和重试
    if (-not $env:UV_HTTP_TIMEOUT) { $env:UV_HTTP_TIMEOUT = '30' }

    if ($uv) {
        # uv 建的 venv 没有 pip，用 uv pip 装（也更快）
        if ($Mirror) {
            Say-Info '按 -Mirror 直接走清华镜像…'
            & $uv.Source pip install --python $venvPython -r $reqFile --index-url $mirror
        }
        else {
            & $uv.Source pip install --python $venvPython -r $reqFile
        }
        if ($LASTEXITCODE -eq 0) { $installed = $true }
        else {
            Say-Warn '默认源安装失败，改用清华镜像重试…'
            & $uv.Source pip install --python $venvPython -r $reqFile --index-url $mirror
            if ($LASTEXITCODE -eq 0) { $installed = $true }
        }
    }

    if (-not $installed) {
        $ErrorActionPreference = 'Continue'
        & $venvPython -m pip --version *> $null
        $hasPip = ($LASTEXITCODE -eq 0)
        if (-not $hasPip) {
            Say-Info 'venv 里没有 pip，先执行 ensurepip…'
            & $venvPython -m ensurepip --upgrade *> $null
        }
        $ErrorActionPreference = $eap
        $pipArgs = @('install', '-r', $reqFile, '--quiet', '--disable-pip-version-check', '--timeout', '60', '--retries', '2')
        if ($Mirror) {
            & $venvPython -m pip @pipArgs -i $mirror
        }
        else {
            & $venvPython -m pip @pipArgs
        }
        if ($LASTEXITCODE -ne 0) {
            Say-Warn '默认源安装失败，改用清华镜像重试…'
            & $venvPython -m pip @pipArgs -i $mirror
        }
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    }

    if (-not $installed) {
        Say-Fail '依赖安装失败（多半是网络）。可以手动试试：'
        Say-Info 'cd backend'
        Say-Info '.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple'
        Say-Info '没有 pip 就先装 uv：uv pip install --python .venv\Scripts\python.exe -r requirements.txt'
        Say-Info '有代理的话先设：set HTTPS_PROXY=http://127.0.0.1:7890   然后重跑 start.bat -Mirror'
        exit 1
    }
    try { (Get-FileHash $reqFile -Algorithm SHA256).Hash | Set-Content $marker -Encoding ASCII } catch { }
    Say-Ok '依赖已安装'
}

# ---------------------------------------------------------------- 3) 端口
function Test-PortBusy {
    param([int]$p)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect('127.0.0.1', $p, $null, $null)
        $done = $iar.AsyncWaitHandle.WaitOne(400, $false)
        if ($done -and $client.Connected) { $client.Close(); return $true }
        $client.Close()
        return $false
    }
    catch { return $false }
}


$usePort = $Port
while ((Test-PortBusy $usePort) -and $usePort -lt ($Port + 10)) {
    Say-Warn "端口 $usePort 被别的程序占用，换下一个…"
    $usePort++
}
if (Test-PortBusy $usePort) {
    Say-Fail "端口 $Port ~ $($Port + 9) 都被占用了，请换个端口：start.bat -Port 8123"
    exit 1
}
$url = 'http://127.0.0.1:' + $usePort

# ---------------------------------------------------------------- 4) 起服务
Say-Info "启动后端（端口 $usePort）…"
$env:PYTHONIOENCODING = 'utf-8'
$proc = Start-Process -FilePath $venvPython `
    -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$usePort") `
    -WorkingDirectory $backend -PassThru -NoNewWindow

$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 1000
    if ($proc.HasExited) { break }
    try {
        $resp = Invoke-WebRequest -Uri "$url/api/health" -TimeoutSec 2 -UseBasicParsing
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    }
    catch { }
    if ($i -eq 12) { Say-Info '第一次启动要建库/灌知识库，可能再等十几秒…' }
}

if (-not $ready) {
    if (-not $proc.HasExited) { try { $proc.Kill() } catch { } }
    Say-Fail '服务没能启动，请看上面窗口里的报错。'
    Say-Info '常见原因：端口被占、MySQL 账号不对（会提示并自动降级 SQLite）、依赖没装全。'
    exit 1
}

Say-Ok "服务已就绪：$url"
if (-not $NoBrowser) {
    try { Start-Process $url } catch { Say-Warn "自动打开浏览器失败，请手动访问 $url" }
    Say-Ok '已尝试在浏览器打开'
}
Write-Host ''
Write-Host '  关掉这个窗口（或按 Ctrl+C）就停止服务' -ForegroundColor DarkGray
Write-Host "  换端口：start.bat -Port 8100        前端热更新开发：scripts\start-frontend.ps1" -ForegroundColor DarkGray
Write-Host ''

Wait-Process -Id $proc.Id
Say-Info '服务已停止'