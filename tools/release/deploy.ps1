# MYTech: build a new version on this PC and put it on the VPS (no GitHub).
#   powershell -ExecutionPolicy Bypass -File tools\release\deploy.ps1
#   -NoDesktop  the server only (no new desktop installer)      -NoApk  skip the phone app
# 1) the next version number (one more than what the VPS has)  2) the desktop installer, built here
# 3) the code and the installer sent to the VPS  4) the VPS: backup, new code, the phone app built there with the
#    same signing key, the server rebuilt and restarted. Every PC and phone then gets «فيه نسخة جديدة».
param([string]$Server = "root@app.wintag.tech", [string]$Url = "https://app.wintag.tech", [switch]$NoDesktop, [switch]$NoApk)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
function Run($what, [scriptblock]$cmd) { & $cmd; if ($LASTEXITCODE -ne 0) { throw "$what فشل" } }

Write-Host "== 1) رقم النسخة" -ForegroundColor Cyan
$last = 0
try {
  $c = Invoke-RestMethod "$Url/api/v1/system/clients" -TimeoutSec 20
  foreach ($k in @("desktop", "android")) { if ($c.$k) { $n = [int]($c.$k.version.Split(".")[-1]); if ($n -gt $last) { $last = $n } } }
} catch { Write-Host "(السيرفر مارَدّش: هكمّل من آخر رقم محفوظ)" }
$saved = Join-Path $Root "tools\release\last-build.txt"
if (Test-Path $saved) { $s = [int](Get-Content $saved); if ($s -gt $last) { $last = $s } }
$build = $last + 1
Run "رقم النسخة" { node tools/release/stamp_version.mjs $build }
$v = (Get-Content VERSION).Trim()
Write-Host "   النسخة الجديدة $v"

$out = Join-Path $env:TEMP "mytech-out"
Remove-Item -Recurse -Force $out -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $out | Out-Null

if (-not $NoDesktop) {
  Write-Host "== 2) برنامج الديسكتوب (أول مرة بتاخد وقت)" -ForegroundColor Cyan
  Push-Location desktop
  try {
    Run "npm ci" { npm ci --no-audit --no-fund }
    Run "اختبارات الواجهة" { npm test }
    Run "فحص الكود" { npm run typecheck }
    Run "بناء الديسكتوب" { npx tauri build }
  } finally { Pop-Location }
  $exe = Get-ChildItem "desktop\src-tauri\target\release\bundle\nsis\*.exe" | Sort-Object LastWriteTime | Select-Object -Last 1
  Copy-Item $exe.FullName (Join-Path $out "MYTech-Desktop-Setup-$v.exe")
}

Write-Host "== 3) رفع الكود على الـVPS" -ForegroundColor Cyan
$tar = Join-Path $out "mytech-src.tar.gz"
Run "تجميع الكود" { tar.exe -czf $tar --exclude=node_modules --exclude=.git --exclude=desktop/src-tauri/target `
  --exclude=.venv --exclude=__pycache__ --exclude=*.pyc --exclude=deploy/vps/clients --exclude=.env `
  --exclude=backend/media --exclude=backend/backups -C $Root . }
Run "الاتصال بالـVPS" { ssh $Server "mkdir -p /opt/mytech-upload" }
Run "الرفع" { scp (Get-ChildItem $out -File | ForEach-Object FullName) "${Server}:/opt/mytech-upload/" }

Write-Host "== 4) تحديث الـVPS (الموبايل بيتبني هناك)" -ForegroundColor Cyan
$skip = if ($NoApk) { "SKIP_APK=1 " } else { "" }
Run "تحديث الـVPS" { ssh -t $Server "${skip}bash /opt/mytech/deploy/vps/update-from-upload.sh" }
Set-Content $saved $build
# a copy of the phone app's signing key on this PC too (without it no phone takes an update): once
$keys = Join-Path $HOME "MYTech-keys"
if (-not $NoApk -and -not (Test-Path (Join-Path $keys "mytech-release.jks"))) {
  New-Item -ItemType Directory -Force $keys | Out-Null
  scp "${Server}:/opt/mytech-keys/*" "$keys\"
  if ($LASTEXITCODE -eq 0) { Write-Host "   مفتاح توقيع الموبايل اتنسخ في $keys — خد منه نسخة على فلاشة وGoogle Drive" -ForegroundColor Yellow }
}
Write-Host "✓ النسخة $v على السيرفر. الأجهزة والموبايلات هيطلعلها «فيه نسخة جديدة»." -ForegroundColor Green
