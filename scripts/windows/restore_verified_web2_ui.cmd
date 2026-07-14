@echo off
setlocal
cd /d "%~dp0\..\.."
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0restore_verified_web2_ui.ps1" -ProjectRoot "%CD%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo ERROR: Web2 restore failed. Read the PowerShell message above.
  pause
)
exit /b %RC%
