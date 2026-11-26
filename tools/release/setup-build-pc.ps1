# MYTech: get this PC ready to build the desktop program and to update the VPS (once).
#   Right-click > Run with PowerShell, or:  powershell -ExecutionPolicy Bypass -File tools\release\setup-build-pc.ps1
# Installs Node.js 22, Rust and the Visual Studio C++ build tools (winget), then makes an SSH key and puts it on the
# VPS, so deploy.ps1 never asks for the VPS password again.
param([string]$Server = "root@app.wintag.tech")
$ErrorActionPreference = "Stop"

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

Write-Host "== 1) البرامج اللي بيتبني بيها الديسكتوب" -ForegroundColor Cyan
if (-not (Have winget)) { throw "winget مش موجود: حدّث ويندوز (App Installer من Microsoft Store)" }
if (-not (Have node)) { winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements }
if (-not (Have rustup)) { winget install -e --id Rustlang.Rustup --accept-source-agreements --accept-package-agreements }
winget install -e --id Microsoft.VisualStudio.2022.BuildTools --accept-source-agreements --accept-package-agreements `
  --override "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
if (Have rustup) { rustup default stable }

Write-Host "== 2) مفتاح الدخول على الـVPS" -ForegroundColor Cyan
$key = Join-Path $HOME ".ssh\id_ed25519"
if (-not (Test-Path $key)) {
  New-Item -ItemType Directory -Force (Join-Path $HOME ".ssh") | Out-Null
  cmd /c "ssh-keygen -q -t ed25519 -N `"`" -f `"$key`""
}
Write-Host "هيطلب باسورد الـroot بتاع الـVPS مرة واحدة بس:"
Get-Content "$key.pub" | ssh $Server "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
ssh -o BatchMode=yes $Server "echo ok" | Out-Null
Write-Host "✓ الجهاز جاهز. اقفل الـPowerShell وافتحه تاني، وبعدها شغّل tools\release\deploy.ps1" -ForegroundColor Green
