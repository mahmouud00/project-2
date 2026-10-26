<#
  MYTech Solutions - stop the server and its PostgreSQL before the installer replaces their files.
  Run by MYTech-Server-Setup.exe (PrepareToInstall) as Administrator. Exit 0 = both stopped (or absent).
  Order: MYTechServer (depends on MYTechPostgreSQL) -> leftover server processes -> MYTechPostgreSQL
  (pg_ctl fast stop as a fallback, then its processes as a last resort; PostgreSQL recovers from its WAL).
#>
param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference = "Continue"
$logDir = Join-Path $Root "logs"
function Log([string]$m) {
  $line = "$(Get-Date -Format s) [stop-services] $m"
  Write-Host $line
  if (Test-Path $logDir) { Add-Content -Path (Join-Path $logDir "install.log") -Value $line -Encoding UTF8 }
}
function Status([string]$name) {
  $s = Get-Service $name -ErrorAction SilentlyContinue
  if ($s) { return [string]$s.Status } else { return "Missing" }
}
function Wait-Stopped([string]$name, [int]$seconds) {
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline) {
    if ((Status $name) -in @("Stopped", "Missing")) { return $true }
    Start-Sleep -Seconds 1
  }
  return $false
}
function Kill-Under([string[]]$names, [string]$folder) {
  foreach ($p in Get-Process -Name $names -ErrorAction SilentlyContinue) {
    $path = $null
    try { $path = $p.Path } catch { }
    if ($path -and $path.StartsWith($folder, [StringComparison]::OrdinalIgnoreCase)) {
      Log "killing $($p.ProcessName) ($($p.Id))"
      Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
  }
}

# 1) MYTech server (WinSW + launcher + server)
if ((Status "MYTechServer") -notin @("Stopped", "Missing")) {
  Log "stopping MYTechServer ($(Status 'MYTechServer'))"
  try { Stop-Service MYTechServer -Force -ErrorAction Stop } catch { Log "Stop-Service MYTechServer: $($_.Exception.Message)" }
  if (-not (Wait-Stopped "MYTechServer" 120)) {
    Log "MYTechServer still $(Status 'MYTechServer'): killing its processes"
    Kill-Under @("MYTechServer", "mytech-service") (Join-Path $Root "service")
    [void](Wait-Stopped "MYTechServer" 30)
  }
}
Kill-Under @("mytech-server") (Join-Path $Root "app")

# 2) PostgreSQL
if ((Status "MYTechPostgreSQL") -notin @("Stopped", "Missing")) {
  Log "stopping MYTechPostgreSQL ($(Status 'MYTechPostgreSQL'))"
  try { Stop-Service MYTechPostgreSQL -Force -ErrorAction Stop } catch { Log "Stop-Service MYTechPostgreSQL: $($_.Exception.Message)" }
  if (-not (Wait-Stopped "MYTechPostgreSQL" 90)) {
    $pgCtl = Join-Path $Root "pgsql\bin\pg_ctl.exe"
    if (Test-Path $pgCtl) {
      Log "MYTechPostgreSQL still $(Status 'MYTechPostgreSQL'): pg_ctl stop -m fast"
      & $pgCtl stop -D (Join-Path $Root "pgdata") -m fast -w -t 60 2>&1 | ForEach-Object { Log "$_" }
    }
    if (-not (Wait-Stopped "MYTechPostgreSQL" 30)) {
      Log "MYTechPostgreSQL still $(Status 'MYTechPostgreSQL'): killing its processes"
      Kill-Under @("postgres", "pg_ctl") (Join-Path $Root "pgsql")
      [void](Wait-Stopped "MYTechPostgreSQL" 30)
    }
  }
}

# 3) anything still running from this folder (e.g. a PostgreSQL left running after its service was
#    removed, or one still shutting down) keeps its files locked: give it a moment, then end it
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
  $left = Get-Process -Name "postgres", "pg_ctl", "mytech-server", "mytech-service" -ErrorAction SilentlyContinue |
    Where-Object { try { $_.Path -and $_.Path.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase) } catch { $false } }
  if (-not $left) { break }
  Start-Sleep -Seconds 1
}
Kill-Under @("postgres", "pg_ctl") (Join-Path $Root "pgsql")
Kill-Under @("mytech-server") (Join-Path $Root "app")
Kill-Under @("mytech-service", "MYTechServer") (Join-Path $Root "service")

$server, $pg = (Status "MYTechServer"), (Status "MYTechPostgreSQL")
Log "MYTechServer: $server, MYTechPostgreSQL: $pg"
if ($server -in @("Stopped", "Missing") -and $pg -in @("Stopped", "Missing")) { exit 0 }
exit 1
