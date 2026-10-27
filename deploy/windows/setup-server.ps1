<#
  MYTech Solutions - offline server setup. Run by the installer (MYTech-Server-Setup.exe) as Administrator.
  Fresh install:  bundled PostgreSQL -> database + roles -> migrations -> company + admin user
                  -> Windows services (MYTechPostgreSQL, MYTechServer) -> firewall -> fingerprint.
  Re-run with a newer version: backup -> migrate with the new version -> switch current.json -> restart.

  Secrets: random passwords go to config\.env (readable by Administrators/SYSTEM only). The PostgreSQL
  superuser password is used once and is not stored. Passwords are passed through the environment or
  files, never on a command line, and never written to the log.
#>
param(
  [Parameter(Mandatory=$true)][string]$Root,
  [Parameter(Mandatory=$true)][string]$Version,
  [string]$CompanyCode = "",
  [string]$CompanyName = "",
  [string]$AdminPasswordFile = "",
  [int]$HttpPort = 8000,
  [int]$PgPort = 5433,
  [int]$UdpPort = 47800
)
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false   # no BOM: Python reads these files

function Write-Utf8([string]$Path, [string]$Text) { [IO.File]::WriteAllText($Path, $Text, $utf8) }
function Log([string]$m) {
  $line = "$(Get-Date -Format s) $m"
  Write-Host $line
  [IO.File]::AppendAllText((Join-Path $Root "logs\install.log"), "$line`r`n", $utf8)
}
function New-Secret([int]$len = 32) {
  $bytes = New-Object byte[] $len
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  return ([Convert]::ToBase64String($bytes) -replace '[+/=]', '').Substring(0, [Math]::Min($len, 40))
}
function Wait-Until([scriptblock]$Test, [int]$Seconds, [string]$What) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) { if (& $Test) { return }; Start-Sleep -Seconds 2 }
  throw "Timed out waiting for $What"
}

foreach ($d in "config", "backups", "media", "license", "logs") { New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null }
$pgBin = Join-Path $Root "pgsql\bin"
$pgData = Join-Path $Root "pgdata"
$versionDir = Join-Path $Root "app\$Version"
$exe = Join-Path $versionDir "mytech-server.exe"
$configDir = Join-Path $Root "config"
$envFile = Join-Path $configDir ".env"
$currentFile = Join-Path $Root "current.json"
$serviceExe = Join-Path $Root "service\MYTechServer.exe"
$fresh = -not (Test-Path $envFile)
Log "setup $Version (fresh=$fresh)"

try {
  # ---------------------------------------------------------------- PostgreSQL (bundled, local only)
  $superPass = $null
  if (-not (Test-Path (Join-Path $pgData "PG_VERSION"))) {
    Log "initialising PostgreSQL data directory"
    New-Item -ItemType Directory -Force -Path $pgData | Out-Null
    & icacls $pgData /grant "NT AUTHORITY\NetworkService:(OI)(CI)F" /T | Out-Null
    $superPass = New-Secret 32
    $pwFile = Join-Path $env:TEMP ("mt-" + [guid]::NewGuid().ToString("N"))
    Write-Utf8 $pwFile $superPass
    try {
      & (Join-Path $pgBin "initdb.exe") -D $pgData -U postgres --pwfile=$pwFile -E UTF8 --locale=C -A scram-sha-256 | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "initdb failed" }
    } finally { Remove-Item -Force $pwFile -ErrorAction SilentlyContinue }
    [IO.File]::AppendAllText((Join-Path $pgData "postgresql.conf"), "`r`nport = $PgPort`r`nlisten_addresses = 'localhost'`r`n", $utf8)
    & icacls $pgData /grant "NT AUTHORITY\NetworkService:(OI)(CI)F" /T | Out-Null
  }
  # Tuning for the server PC's memory (20-40 people at once). Rewritten on every install/upgrade; read at start.
  $ramMb = [int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB)
  $sharedMb = [Math]::Max(128, [Math]::Min(4096, [int]($ramMb / 4)))
  $cacheMb = [Math]::Max(512, [int]($ramMb / 2))
  Write-Utf8 (Join-Path $pgData "mytech-tuning.conf") ("max_connections = 150`r`nshared_buffers = ${sharedMb}MB`r`n" +
    "effective_cache_size = ${cacheMb}MB`r`nwork_mem = 16MB`r`nmaintenance_work_mem = 256MB`r`n" +
    "random_page_cost = 1.1`r`nwal_compression = on`r`n")
  $pgConf = Join-Path $pgData "postgresql.conf"
  if (-not (Select-String -Path $pgConf -Pattern "mytech-tuning.conf" -SimpleMatch -Quiet)) {
    [IO.File]::AppendAllText($pgConf, "`r`ninclude_if_exists = 'mytech-tuning.conf'`r`n", $utf8)
  }
  Log "PostgreSQL tuned for ${ramMb} MB RAM (shared_buffers ${sharedMb} MB)"
  if (-not (Get-Service MYTechPostgreSQL -ErrorAction SilentlyContinue)) {
    Log "registering PostgreSQL service"
    & (Join-Path $pgBin "pg_ctl.exe") register -N MYTechPostgreSQL -D $pgData -S auto -U "NT AUTHORITY\NetworkService" | Out-Null
  }
  Start-Service MYTechPostgreSQL
  $isReady = Join-Path $pgBin "pg_isready.exe"
  Wait-Until { & $isReady -h localhost -p $PgPort -q; $LASTEXITCODE -eq 0 } 60 "PostgreSQL"
  Log "PostgreSQL running on localhost:$PgPort"

  # ---------------------------------------------------------------- settings
  if ($fresh) {
    $app = New-Secret 28; $sys = New-Secret 28; $own = New-Secret 28; $jwt = New-Secret 40
    $settings = @"
APP_MODE=offline
DATABASE_URL=postgresql+psycopg://mytech_app:$app@localhost:$PgPort/mytech
DATABASE_SYSTEM_URL=postgresql+psycopg://mytech_system:$sys@localhost:$PgPort/mytech
DATABASE_OWNER_URL=postgresql+psycopg://mytech_owner:$own@localhost:$PgPort/mytech
JWT_SECRET=$jwt
LICENSE_FILE=$Root\license\license.json
MEDIA_DIR=$Root\media
BACKUP_DIR=$Root\backups
BACKUP_KEEP=14
BACKUP_HOUR=2
PG_BIN_DIR=$pgBin
HTTP_PORT=$HttpPort
DISCOVERY_UDP_PORT=$UdpPort
"@
    Write-Utf8 $envFile $settings
    & icacls $envFile /inheritance:r /grant:r "Administrators:F" "SYSTEM:F" | Out-Null
    Log "settings written (secrets generated)"
  }

  # ---------------------------------------------------------------- service stop (re-run / upgrade)
  if (Get-Service MYTechServer -ErrorAction SilentlyContinue) {
    Log "stopping MYTech service"
    Stop-Service MYTechServer -ErrorAction SilentlyContinue
  }

  Push-Location $configDir
  try {
    if ($fresh) {
      if (-not $superPass) { throw "PostgreSQL already initialised but this is a fresh MYTech install; use an empty folder" }
      $env:MYTECH_ADMIN_URL = "postgresql+psycopg://postgres:$superPass@localhost:$PgPort/postgres"
      try { & $exe init-db; if ($LASTEXITCODE -ne 0) { throw "init-db failed" } }
      finally { Remove-Item Env:\MYTECH_ADMIN_URL -ErrorAction SilentlyContinue }
      Log "database and roles created"
    } else {
      Log "backup before upgrade"
      & $exe backup --label "pre-setup-$Version" | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "backup failed; nothing was changed" }
    }
    & $exe migrate
    if ($LASTEXITCODE -ne 0) { throw "migrations failed" }
    Log "database migrated"
    if ($fresh -and $CompanyCode -and $AdminPasswordFile -and (Test-Path $AdminPasswordFile)) {
      $env:MYTECH_NEW_PASSWORD = [IO.File]::ReadAllText($AdminPasswordFile).Trim()
      try { & $exe create-company --code $CompanyCode --name $CompanyName --admin admin | Out-Null; if ($LASTEXITCODE -ne 0) { throw "create-company failed" } }
      finally { Remove-Item Env:\MYTECH_NEW_PASSWORD -ErrorAction SilentlyContinue; Remove-Item -Force $AdminPasswordFile -ErrorAction SilentlyContinue }
      Log "company $CompanyCode created (user: admin)"
    }
  } finally { Pop-Location }

  # ---------------------------------------------------------------- switch version + service
  $previous = $null
  if (Test-Path $currentFile) { $previous = Get-Content -Raw $currentFile | ConvertFrom-Json }
  $state = [ordered]@{ version = $Version; path = "app/$Version"; updated_at = (Get-Date).ToUniversalTime().ToString("o") }
  if ($previous -and $previous.version -ne $Version) { $state.previous = $previous }
  Write-Utf8 $currentFile ($state | ConvertTo-Json -Depth 6)

  if (-not (Get-Service MYTechServer -ErrorAction SilentlyContinue)) {
    & $serviceExe install | Out-Null
    Log "MYTech service installed"
  }
  # restart after a failure (turned off by stop-services.ps1 while the files were replaced)
  & sc.exe failure MYTechServer reset= 3600 actions= restart/10000/restart/30000 | Out-Null
  # Any network profile: factory Wi-Fi is often marked "Public" by Windows, and then the other PCs cannot
  # reach the server at all. Only the MYTech port and the discovery port are opened (owner's decision).
  # Older installs had Private/Domain only; their rules are widened here.
  foreach ($rule in @(@{ Name = "MYTech API"; Protocol = "TCP"; Port = $HttpPort },
                      @{ Name = "MYTech Discovery"; Protocol = "UDP"; Port = $UdpPort })) {
    if (Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue) {
      Set-NetFirewallRule -DisplayName $rule.Name -Profile Any -Enabled True
    } else {
      New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Protocol $rule.Protocol -LocalPort $rule.Port `
        -Action Allow -Profile Any | Out-Null
    }
  }
  Log "firewall rules for ports $HttpPort/TCP and $UdpPort/UDP (all network profiles)"
  Start-Service MYTechServer
  Wait-Until { try { (Invoke-WebRequest -UseBasicParsing "http://localhost:$HttpPort/api/v1/system/health" -TimeoutSec 3).StatusCode -eq 200 } catch { $false } } 90 "MYTech server"
  Log "MYTech server running on port $HttpPort"

  $fp = (& $exe fingerprint | Select-Object -Last 1).Trim()
  Write-Utf8 (Join-Path $Root "license\fingerprint.txt") $fp
  Log "machine fingerprint saved to license\fingerprint.txt"
  exit 0
} catch {
  Log "FAILED: $($_.Exception.Message)"
  exit 1
}
