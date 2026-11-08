@echo off
chcp 65001 >nul
title 用调试端口启动 Edge（给屏幕演示读网页结构用）

REM ------------------------------------------------------------------
REM  为什么需要这个：
REM  浏览器只有在**启动时**带 --remote-debugging-port 才会开放调试端口，
REM  已经开着的 Edge 事后挂不上。带上这个参数启动后，CodeMentor 的屏幕演示
REM  就能直接读网页 DOM（知道每道题哪个选项被选中），并用 DOM 点击选项，
REM  不用再靠截图认像素。
REM
REM  注意：会先关掉当前所有 Edge 窗口。Edge 重新打开时一般会恢复标签页，
REM  如果没恢复，可以在 Edge 设置里打开「启动时 → 继续浏览上次打开的网页」。
REM ------------------------------------------------------------------

set PORT=9222
set EDGE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
if not exist "%EDGE%" set EDGE=C:\Program Files\Microsoft\Edge\Application\msedge.exe
if not exist "%EDGE%" (
  echo 没找到 Edge，请手动改脚本里的 EDGE 路径。
  pause
  exit /b 1
)

echo 关闭正在运行的 Edge...
taskkill /IM msedge.exe /F >nul 2>&1
timeout /t 2 >nul

echo 以调试端口 %PORT% 启动 Edge...
start "" "%EDGE%" --remote-debugging-port=%PORT%

echo.
echo 已启动。请在这个 Edge 里打开你的答题页面，然后回到 CodeMentor 开始屏幕演示。
echo 验证方式：浏览器访问 http://127.0.0.1:%PORT%/json/list ，能看到页面列表就说明成功。
echo.
pause