# 启动前端开发服务器（Vite + HMR）
# 需要先启动后端（scripts/start-backend.ps1）
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"

Push-Location $frontend
if (-not (Test-Path "node_modules")) {
    Write-Host "[!] 首次运行，正在安装依赖…" -ForegroundColor Yellow
    pnpm install
}
Write-Host "前端启动中: http://127.0.0.1:5173  (API 代理到 8000)" -ForegroundColor Green
pnpm dev
Pop-Location