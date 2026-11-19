$ErrorActionPreference = 'SilentlyContinue'
$InfoFile = Join-Path $env:LOCALAPPDATA 'WinRemote\connection.json'
if (-not (Test-Path $InfoFile)) { exit 0 }
try {
    $Info = Get-Content -Raw -Path $InfoFile | ConvertFrom-Json
    $PidToStop = [int]$Info.pid
    $ExpectedPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    $ExpectedScript = Join-Path $PSScriptRoot 'server.py'
    $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $PidToStop" -ErrorAction Stop
    if ($Process.ExecutablePath -ieq $ExpectedPython -and $Process.CommandLine -like "*$ExpectedScript*") {
        Stop-Process -Id $PidToStop -Force
    }
} catch { }
Remove-Item $InfoFile -Force -ErrorAction SilentlyContinue
