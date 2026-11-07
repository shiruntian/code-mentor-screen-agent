param(
    [switch]$NoFrontend
)
# 一键启动开发模式：后端(8000) + 前端开发服务器(5173，热更新)
# 只想看效果/给老师演示：直接双击根目录的 start.bat（只起后端，前端用打好的 dist）
$root = Split-Path -Parent $PSScriptRoot

# Windows 自带的是 powershell.exe，装了 PowerShell 7 才有 pwsh
$shell = 'powershell'
$pwshPath = Get-Command pwsh -ErrorAction SilentlyContinue
if ($pwshPath) { $shell = $pwshPath.Source }

Write-Host "=== CodeMentor 开发模式启动 ===" -ForegroundColor Cyan
Write-Host "（等两个窗口都起来后访问 http://127.0.0.1:5173）" -ForegroundColor DarkGray

# 后端
$backendScript = Join-Path $PSScriptRoot "start-backend.ps1"
$backend = Start-Process $shell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$backendScript`"" -PassThru
Write-Host "后端 PID $($backend.Id)  -> http://127.0.0.1:8000" -ForegroundColor Green

Start-Sleep -Seconds 3

if (-not $NoFrontend) {
    $frontendScript = Join-Path $PSScriptRoot "start-frontend.ps1"
    $frontend = Start-Process $shell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$frontendScript`"" -PassThru
    Write-Host "前端 PID $($frontend.Id) -> http://127.0.0.1:5173" -ForegroundColor Green
}

Write-Host ""
Write-Host "只想要一个地址的话：双击 start.bat，或直接访问 http://127.0.0.1:8000（后端托管 dist）" -ForegroundColor DarkGray
Write-Host "关闭上面的窗口即可停止服务。" -ForegroundColor DarkGray