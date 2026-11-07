@echo off
rem ============================================================
rem  CodeMentor - one click start (Windows)
rem  Just double click this file. Closing the window stops it.
rem
rem  Options:  start.bat -Port 8100     use another port
rem            start.bat -NoBrowser     do not open the browser
rem            start.bat -Reinstall     force reinstall deps
rem            start.bat -Mirror        use Tsinghua PyPI mirror first
rem ============================================================
setlocal
cd /d "%~dp0"

title CodeMentor
echo.
echo   ==========================================================
echo    CodeMentor - starting
echo    First run creates a venv and installs deps (a few minutes)
echo   ==========================================================
echo.

powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" (
  echo   [!] startup failed, exit code %CODE%
  echo.
  pause
) else (
  echo   [i] service stopped.
  timeout /t 3 >nul
)
endlocal