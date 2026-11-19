@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo WinRemote is not installed. Run Install WinRemote.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "brightness_diagnostics.py" > "%USERPROFILE%\Desktop\WinRemote-brightness-diagnostic.txt" 2>&1
type "%USERPROFILE%\Desktop\WinRemote-brightness-diagnostic.txt"
echo.
echo Diagnostic saved to your Desktop as WinRemote-brightness-diagnostic.txt
pause
