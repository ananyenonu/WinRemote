@echo off
setlocal
cd /d "%~dp0"

set "PS_EXE="
where pwsh >nul 2>nul
if not errorlevel 1 set "PS_EXE=pwsh"
if not defined PS_EXE if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" set "PS_EXE=%ProgramFiles%\PowerShell\7\pwsh.exe"
if not defined PS_EXE if exist "%LocalAppData%\Programs\PowerShell\7\pwsh.exe" set "PS_EXE=%LocalAppData%\Programs\PowerShell\7\pwsh.exe"
if not defined PS_EXE if exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not defined PS_EXE (
    echo Could not find PowerShell 7 or Windows PowerShell.
    echo Install PowerShell, then run this file again.
    pause
    exit /b 1
)

"%PS_EXE%" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo.
pause
exit /b %RESULT%
