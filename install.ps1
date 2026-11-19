$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host "`nWinRemote setup" -ForegroundColor Cyan

$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    try { & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"; if ($LASTEXITCODE -eq 0) { $Python = 'py' } } catch { }
}
if (-not $Python -and (Get-Command python -ErrorAction SilentlyContinue)) {
    try { & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"; if ($LASTEXITCODE -eq 0) { $Python = 'python' } } catch { }
}
if (-not $Python) {
    Write-Host "Python 3.10 or newer was not found. Install it from https://www.python.org/downloads/windows/ and enable 'Add python.exe to PATH'." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    if ($Python -eq 'py') { & py -3 -m venv .venv } else { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
}
$VenvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Could not update pip.' }
& $VenvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Could not install WinRemote dependencies.' }

# Create one-click launch shortcuts and a per-user logon startup shortcut.
$PowerShellExe = $null
if (Get-Command pwsh -ErrorAction SilentlyContinue) { $PowerShellExe = (Get-Command pwsh).Source }
if (-not $PowerShellExe -and (Test-Path "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe")) { $PowerShellExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" }
if (-not $PowerShellExe) { throw 'PowerShell could not be found to create WinRemote shortcuts.' }

$Desktop = [Environment]::GetFolderPath('Desktop')
$StartMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\WinRemote'
$Startup = [Environment]::GetFolderPath('Startup')
New-Item -ItemType Directory -Force -Path $StartMenu | Out-Null
$Wsh = New-Object -ComObject WScript.Shell
function New-WinRemoteShortcut([string]$Path, [string]$ScriptName, [string]$Arguments = '') {
    $scriptPath = Join-Path $PSScriptRoot $ScriptName
    $shortcut = $Wsh.CreateShortcut($Path)
    $shortcut.TargetPath = $PowerShellExe
    $shortcut.Arguments = "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`" $Arguments"
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.Description = 'Start or show WinRemote connection details'
    $shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,109"
    $shortcut.Save()
}
New-WinRemoteShortcut (Join-Path $Desktop 'WinRemote.lnk') 'Start WinRemote Background.ps1'
New-WinRemoteShortcut (Join-Path $StartMenu 'WinRemote.lnk') 'Start WinRemote Background.ps1'
New-WinRemoteShortcut (Join-Path $StartMenu 'Show connection details.lnk') 'Show WinRemote Details.ps1'
New-WinRemoteShortcut (Join-Path $StartMenu 'Stop WinRemote.lnk') 'Stop WinRemote.ps1'
New-WinRemoteShortcut (Join-Path $Startup 'WinRemote.lnk') 'Start WinRemote Background.ps1' '-Quiet'

Write-Host "`nShortcuts created:" -ForegroundColor Green
Write-Host '  Desktop: WinRemote'
Write-Host '  Startup: WinRemote starts quietly when you sign in to Windows'
Write-Host '  Start Menu: WinRemote, Show connection details, Stop WinRemote'
Write-Host "`nStarting WinRemote in the background...`n" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'Start WinRemote Background.ps1')
