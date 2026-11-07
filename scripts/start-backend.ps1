param(
    [int]$Port = 8000,
    [switch]$Reload
)
# 启动后端（Windows PowerShell 5.1 / PowerShell 7 都可用）
# 日常只想看界面：双击根目录 start.bat 更省事（会自动建环境、装依赖、开浏览器）
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "[!] 未找到虚拟环境，正在创建…" -ForegroundColor Yellow
    Push-Location $backend
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        uv venv --python 3.12 .venv
        uv pip install --python .venv\Scripts\python.exe -r requirements.txt
    }
    else {
        $sys = Get-Command python -ErrorAction SilentlyContinue
        if (-not $sys) { $sys = Get-Command py -ErrorAction SilentlyContinue }
        if (-not $sys) {
            Write-Host "[×] 没找到 Python，请先安装 Python 3.10+ 并勾选 Add to PATH" -ForegroundColor Red
            Pop-Location
            exit 1
        }
        & $sys.Source -m venv .venv
        .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    }
    Pop-Location
}

$env:PYTHONIOENCODING = "utf-8"
Push-Location $backend
Write-Host "后端启动中: http://127.0.0.1:$Port  (API 文档 /docs)" -ForegroundColor Green
if ($Reload) {
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port --reload
}
else {
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port
}
Pop-Location