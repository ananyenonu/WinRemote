param([switch]$Quiet)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$AppDir = $PSScriptRoot
$Python = Join-Path $AppDir '.venv\Scripts\python.exe'
$StateDir = Join-Path $env:LOCALAPPDATA 'WinRemote'
$InfoFile = Join-Path $StateDir 'connection.json'
$LogOut = Join-Path $StateDir 'launcher-out.log'
$LogErr = Join-Path $StateDir 'launcher-error.log'

function Get-ConnectionInfo {
    if (Test-Path $InfoFile) {
        try { return (Get-Content -Raw -Path $InfoFile | ConvertFrom-Json) } catch { }
    }
    return $null
}
function Test-WinRemoteReady($Info) {
    if ($null -eq $Info) { return $false }
    try {
        $p = Get-Process -Id ([int]$Info.pid) -ErrorAction Stop
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $result = $client.BeginConnect('127.0.0.1', [int]$Info.port, $null, $null)
            if (-not $result.AsyncWaitHandle.WaitOne(1000)) { return $false }
            $client.EndConnect($result)
            return $true
        } finally { $client.Close() }
    } catch { return $false }
}

if (-not (Test-Path $Python)) {
    [System.Windows.Forms.MessageBox]::Show('WinRemote is not installed. Run Install WinRemote.bat first.', 'WinRemote') | Out-Null
    exit 1
}
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$Info = Get-ConnectionInfo
if (-not (Test-WinRemoteReady $Info)) {
    if (Test-Path $InfoFile) { Remove-Item $InfoFile -Force -ErrorAction SilentlyContinue }
    Start-Process -FilePath $Python -ArgumentList @('server.py') -WorkingDirectory $AppDir -WindowStyle Hidden -RedirectStandardOutput $LogOut -RedirectStandardError $LogErr | Out-Null
}

$Ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    $Info = Get-ConnectionInfo
    if (Test-WinRemoteReady $Info) { $Ready = $true; break }
}
if (-not $Ready) {
    $message = "WinRemote did not start. Check the log files in:`r`n$StateDir`r`n`r`nIf port 8765 is already in use, close the other application using it."
    if (-not $Quiet) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show($message, 'WinRemote', 'OK', 'Error') | Out-Null
    }
    exit 1
}

if (-not $Quiet) {
    & (Join-Path $AppDir 'Show WinRemote Details.ps1')
}
