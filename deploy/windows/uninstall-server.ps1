<#
  Called by the uninstaller: stops and removes the two Windows services and the firewall rules.
  The data (pgdata, backups, media, license, config) is KEPT; delete the folder by hand only after
  copying the backups somewhere safe.
#>
param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference = "Continue"
# stop both services (and anything still running from this folder) BEFORE removing them: removing a
# running PostgreSQL service leaves postgres.exe running with its files locked
& (Join-Path $PSScriptRoot "stop-services.ps1") -Root $Root
if (Get-Service MYTechServer -ErrorAction SilentlyContinue) {
  & (Join-Path $Root "service\MYTechServer.exe") uninstall | Out-Null
}
if (Get-Service MYTechPostgreSQL -ErrorAction SilentlyContinue) {
  & (Join-Path $Root "pgsql\bin\pg_ctl.exe") unregister -N MYTechPostgreSQL | Out-Null
}
Get-NetFirewallRule -DisplayName "MYTech API", "MYTech Discovery" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
exit 0
