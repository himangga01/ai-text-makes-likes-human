@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if /I "%~1"=="--dry-run" (
  echo START:npm.cmd start
  echo URL:http://localhost:7882
  exit /b 0
)

if not exist "dist\server.js" (
  call setup-portal.cmd || exit /b 1
)

start "" /b powershell.exe -NoProfile -WindowStyle Hidden -Command "$deadline=(Get-Date).AddSeconds(30); while((Get-Date)-lt $deadline){try{$r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 http://localhost:7882/api/health;if($r.StatusCode -in 200,503){Start-Process 'http://localhost:7882';exit}}catch{};Start-Sleep -Milliseconds 500}"

echo Portal is starting.
echo Keep this window open. Press Ctrl+C or close the window to stop.
echo.
call npm.cmd start
exit /b %ERRORLEVEL%
