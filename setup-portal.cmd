@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "CHECK_ONLY=0"
if /I "%~1"=="--check" set "CHECK_ONLY=1"

where node >nul 2>nul || goto :missing_node
echo CHECK:Node.js
where python >nul 2>nul || goto :missing_python
echo CHECK:Python
where codex >nul 2>nul || goto :missing_codex
codex login status >nul 2>nul || goto :login_failed
echo CHECK:Codex login

if "%CHECK_ONLY%"=="1" (
  echo CHECK_OK
  exit /b 0
)

echo Installing portal dependencies...
call npm.cmd ci || goto :failed
echo Building the portal...
call npm.cmd run build || goto :failed
echo.
echo Setup complete. Double-click start-portal.cmd to run the portal.
echo To allow other Wi-Fi PCs, run scripts\allow-lan-firewall.ps1 once as Administrator.
pause
exit /b 0

:missing_node
echo Node.js is not installed.
goto :failed
:missing_python
echo Python is not installed.
goto :failed
:missing_codex
echo Codex CLI is not installed.
goto :failed
:login_failed
echo Codex is not logged in. Run codex login first.
goto :failed
:failed
echo Setup failed. Review the message above.
if not "%CHECK_ONLY%"=="1" pause
exit /b 1
