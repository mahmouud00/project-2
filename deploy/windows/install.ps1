<#
  MYTech Solutions - offline server installation (run as Administrator).

  Prerequisites on the server PC:
    - PostgreSQL 16 for Windows installed as a service (postgresql-x64-16), superuser password known.
  Contents of the installation folder (prepared as described in docs/INSTALL.md "تجهيز فولدر التسطيب"):
    python\            embeddable Python 3.12 (with pip-free site-packages support)
    app\<version>\     server code + site-packages
    service\           launcher.py, MYTechServer.xml, MYTechServer.exe (WinSW)
    current.json
  Usage:
    powershell -ExecutionPolicy Bypass -File install.ps1 -Root C:\MYTech -CompanyCode ACME -CompanyName "ACME"
#>
param(
  [string]$Root = "C:\MYTech",
  [Parameter(Mandatory=$true)][string]$CompanyCode,
  [Parameter(Mandatory=$true)][string]$CompanyName,
  [string]$PgHost = "localhost",
  [int]$PgPort = 5432,
  [int]$HttpPort = 8000,
  [int]$UdpPort = 47800
)
$ErrorActionPreference = "Stop"

function New-Secret([int]$len = 48) {
  $bytes = New-Object byte[] $len
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  return [Convert]::ToBase64String($bytes).Replace('+','A').Replace('/','B').Replace('=','')
}

$python = Join-Path $Root "python\python.exe"
$current = Get-Content (Join-Path $Root "current.json") | ConvertFrom-Json
$versionDir = Join-Path $Root $current.path
foreach ($d in "config","backups","media","license","logs") { New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null }

$pgSuper = Read-Host -AsSecureString "PostgreSQL superuser (postgres) password"
$pgSuperPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pgSuper))

$envFile = Join-Path $Root "config\.env"
if (-not (Test-Path $envFile)) {
  $app = New-Secret 24; $sys = New-Secret 24; $own = New-Secret 24; $jwt = New-Secret 64
@"
APP_MODE=offline
DATABASE_URL=postgresql+psycopg://mytech_app:$app@${PgHost}:$PgPort/mytech
DATABASE_SYSTEM_URL=postgresql+psycopg://mytech_system:$sys@${PgHost}:$PgPort/mytech
DATABASE_OWNER_URL=postgresql+psycopg://mytech_owner:$own@${PgHost}:$PgPort/mytech
JWT_SECRET=$jwt
LICENSE_FILE=$Root\license\license.json
MEDIA_DIR=$Root\media
BACKUP_DIR=$Root\backups
BACKUP_KEEP=14
BACKUP_HOUR=2
PG_BIN_DIR=C:\Program Files\PostgreSQL\16\bin
HTTP_PORT=$HttpPort
DISCOVERY_UDP_PORT=$UdpPort
"@ | Set-Content -Encoding UTF8 $envFile
  # only Administrators and SYSTEM may read the secrets
  icacls $envFile /inheritance:r /grant:r "Administrators:F" "SYSTEM:F" | Out-Null
}

$env:PYTHONPATH = "$versionDir;$versionDir\site-packages"
Push-Location (Join-Path $Root "config")
& $python -m app.cli init-db --admin-url "postgresql+psycopg://postgres:$pgSuperPlain@${PgHost}:$PgPort/postgres"
& $python -m app.cli migrate
$adminPass = Read-Host "Password for the company admin user 'admin'"
& $python -m app.cli create-company --code $CompanyCode --name $CompanyName --admin admin --password $adminPass
Pop-Location

# Windows service (WinSW) + firewall
& (Join-Path $Root "service\MYTechServer.exe") install
New-NetFirewallRule -DisplayName "MYTech API" -Direction Inbound -Protocol TCP -LocalPort $HttpPort -Action Allow -Profile Private,Domain | Out-Null
New-NetFirewallRule -DisplayName "MYTech Discovery" -Direction Inbound -Protocol UDP -LocalPort $UdpPort -Action Allow -Profile Private,Domain | Out-Null
& (Join-Path $Root "service\MYTechServer.exe") start

Start-Sleep -Seconds 5
Write-Host "Server fingerprint for the licence request:"
& $python -c "import sys; sys.path[:0]=[r'$versionDir', r'$versionDir\site-packages']; from app.licensing.fingerprint import machine_fingerprint; print(machine_fingerprint())"
Write-Host "Done. Send the fingerprint to MYTech, then upload the licence from the admin screen (POST /api/v1/system/license)."
