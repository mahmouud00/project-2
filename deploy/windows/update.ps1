<#
  Apply a MYTech update file (*.mtu). Run as Administrator on the server:
    powershell -ExecutionPolicy Bypass -File C:\MYTech\scripts\update.ps1 -Package D:\mytech-1.3.0.mtu
  Verifies the MYTech signature, backs up the database first, migrates with the new version, health-checks it,
  and rolls everything back (database + version) if anything fails. Log: C:\MYTech\logs\updates.log
#>
param([Parameter(Mandatory=$true)][string]$Package, [string]$Root = "C:\MYTech", [int]$HttpPort = 8000)
$ErrorActionPreference = "Stop"
$current = Get-Content -Raw (Join-Path $Root "current.json") | ConvertFrom-Json
$exe = Join-Path (Join-Path $Root $current.path) "mytech-server.exe"
Push-Location (Join-Path $Root "config")
try { & $exe update $Package --root $Root --port $HttpPort; $code = $LASTEXITCODE } finally { Pop-Location }
if ($code -ne 0) { Write-Host "Update failed and was rolled back. See $Root\logs\updates.log"; exit $code }
Write-Host "Update installed."
