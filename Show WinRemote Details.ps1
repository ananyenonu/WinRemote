$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$InfoFile = Join-Path $env:LOCALAPPDATA 'WinRemote\connection.json'
if (-not (Test-Path $InfoFile)) {
    [System.Windows.Forms.MessageBox]::Show('WinRemote is not running. Start it using the WinRemote shortcut.', 'WinRemote') | Out-Null
    exit 1
}
try { $Info = Get-Content -Raw -Path $InfoFile | ConvertFrom-Json } catch {
    [System.Windows.Forms.MessageBox]::Show('Could not read WinRemote connection details. Start WinRemote again.', 'WinRemote') | Out-Null
    exit 1
}
try {
    $null = Get-Process -Id ([int]$Info.pid) -ErrorAction Stop
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect('127.0.0.1', [int]$Info.port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne(2000)) { throw 'Connection timed out' }
        $client.EndConnect($result)
    } finally { $client.Close() }
} catch {
    [System.Windows.Forms.MessageBox]::Show('WinRemote is not currently running. Start it using the WinRemote shortcut.', 'WinRemote') | Out-Null
    exit 1
}

$lines = @()
foreach ($entry in @($Info.addresses)) {
    if ($entry.url) { $lines += "$($entry.label): $($entry.url)" }
}
if ($lines.Count -eq 0) { $lines += 'No network address yet. Check that Wi-Fi is connected, then reopen this window.' }
$CertPath = Join-Path $env:LOCALAPPDATA 'WinRemote\WinRemote-Root-CA.cer'
$text = "Device: $($Info.device)`r`n`r`n$($lines -join "`r`n")`r`n`r`nPairing code: $($Info.pairing_code)`r`n`r`nHTTPS certificate: $CertPath`r`n`r`nBefore first use on Android, copy this .cer file to your phone. In Android Settings, search for 'Install a certificate' and install it as a CA certificate. Then reopen the HTTPS URL in Chrome and choose Install app from Chrome's menu. Keep the pairing code private."

$form = New-Object System.Windows.Forms.Form
$form.Text = 'WinRemote connection details'
$form.Size = New-Object System.Drawing.Size(650, 460)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true

$heading = New-Object System.Windows.Forms.Label
$heading.Text = 'WinRemote is running in the background'
$heading.Font = New-Object System.Drawing.Font('Segoe UI', 12, [System.Drawing.FontStyle]::Bold)
$heading.Location = New-Object System.Drawing.Point(18, 16)
$heading.Size = New-Object System.Drawing.Size(510, 28)
$form.Controls.Add($heading)

$box = New-Object System.Windows.Forms.TextBox
$box.Multiline = $true
$box.ReadOnly = $true
$box.ScrollBars = 'Vertical'
$box.Font = New-Object System.Drawing.Font('Consolas', 10)
$box.Location = New-Object System.Drawing.Point(18, 55)
$box.Size = New-Object System.Drawing.Size(600, 300)
$box.Text = $text
$form.Controls.Add($box)

$copy = New-Object System.Windows.Forms.Button
$copy.Text = 'Copy details'
$copy.Location = New-Object System.Drawing.Point(18, 375)
$copy.Size = New-Object System.Drawing.Size(115, 32)
$copy.Add_Click({ [System.Windows.Forms.Clipboard]::SetText($box.Text) })
$form.Controls.Add($copy)

$close = New-Object System.Windows.Forms.Button
$close.Text = 'Close'
$close.Location = New-Object System.Drawing.Point(503, 375)
$close.Size = New-Object System.Drawing.Size(115, 32)
$close.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.Controls.Add($close)
$form.AcceptButton = $close
$form.ShowDialog() | Out-Null
