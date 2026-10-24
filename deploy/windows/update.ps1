<#
  Apply a MYTech update file (*.mtu). Run as Administrator on the server.
    powershell -ExecutionPolicy Bypass -File update.ps1 -Package D:\mytech-1.3.0.mtu
  The updater backs up the database first and rolls everything back if anything fails.
#>
param([Parameter(Mandatory=$true)][string]$Package, [string]$Root = "C:\MYTech", [int]$HttpPort = 8000)
$ErrorActionPreference = "Stop"
$current = Get-Content (Join-Path $Root "current.json") | ConvertFrom-Json
$versionDir = Join-Path $Root $current.path
$env:PYTHONPATH = "$versionDir;$versionDir\site-packages"
Push-Location (Join-Path $Root "config")
& (Join-Path $Root "python\python.exe") -m app.ops.updater $Package --root $Root --port $HttpPort
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Write-Host "Update failed and was rolled back. See $Root\logs\updates.log"; exit $code }
Write-Host "Update installed."
