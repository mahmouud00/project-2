<#
  Called by the uninstaller: stops and removes the two Windows services and the firewall rules.
  The data (pgdata, backups, media, license, config) is KEPT; delete the folder by hand only after
  copying the backups somewhere safe.
#>
param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference = "Continue"
if (Get-Service MYTechServer -ErrorAction SilentlyContinue) {
  Stop-Service MYTechServer -ErrorAction SilentlyContinue
  & (Join-Path $Root "service\MYTechServer.exe") uninstall | Out-Null
}
if (Get-Service MYTechPostgreSQL -ErrorAction SilentlyContinue) {
  Stop-Service MYTechPostgreSQL -ErrorAction SilentlyContinue
  & (Join-Path $Root "pgsql\bin\pg_ctl.exe") unregister -N MYTechPostgreSQL | Out-Null
}
Get-NetFirewallRule -DisplayName "MYTech API", "MYTech Discovery" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
exit 0
