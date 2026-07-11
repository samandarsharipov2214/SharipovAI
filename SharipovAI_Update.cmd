@echo off
setlocal
set "PROJECT=D:\SharipovAI_Server\SharipovAI"
if not exist "%PROJECT%\scripts\windows\update_pc_node.ps1" set "PROJECT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT%\scripts\windows\update_pc_node.ps1"
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" (
  echo SharipovAI update failed. Read the message above.
) else (
  echo SharipovAI update completed successfully.
)
pause
exit /b %EXITCODE%
