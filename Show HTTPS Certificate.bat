@echo off
set "CERT=%LOCALAPPDATA%\WinRemote\WinRemote-Root-CA.cer"
if not exist "%CERT%" (
  echo WinRemote HTTPS certificate has not been created yet.
  echo Start WinRemote first, then run this file again.
  pause
  exit /b 1
)
start "" explorer.exe /select,"%CERT%"
echo Copy this certificate to your Android phone.
echo On Android Settings, search for Install a certificate, then install it as a CA certificate.
pause
