#!/usr/bin/env bash
# Update the VPS from what your PC uploaded (no GitHub): tools/release/deploy.ps1 sends the code to
# /opt/mytech-upload/mytech-src.tar.gz (and the new desktop installer next to it), then runs this.
#   1) backup  2) the new code into /opt/mytech (the secrets .env and the clients stay)  3) the desktop installer
#   into ./clients  4) the phone app built here (build-apk.sh)  5) the server rebuilt and restarted (it migrates by itself)
set -euo pipefail
cd "$(dirname "$0")"
HERE=$(pwd)
ROOT=$(cd ../.. && pwd)
UP=/opt/mytech-upload
[ -s "$UP/mytech-src.tar.gz" ] || { echo "مفيش كود مرفوع في $UP"; exit 1; }
command -v rsync >/dev/null 2>&1 || apt-get install -y rsync >/dev/null

echo "== 1) نسخة احتياطية"
docker compose exec -T api python -m app.cli backup --label before-update || echo "(مفيش نسخة: السيرفر مش شغال)"

echo "== 2) الكود الجديد"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
tar -xzf "$UP/mytech-src.tar.gz" -C "$STAGE"
[ -f "$STAGE/VERSION" ] && [ -d "$STAGE/backend" ] || { echo "الملف المرفوع مش كود MYTech"; exit 1; }
for d in backend desktop tools docs deploy; do
  [ -d "$STAGE/$d" ] && rsync -a --delete --exclude 'vps/.env' --exclude 'vps/clients/' "$STAGE/$d"/ "$ROOT/$d"/
done
find "$STAGE" -maxdepth 1 -type f -exec cp {} "$ROOT"/ \;
V=$(tr -d '[:space:]' < "$ROOT/VERSION")
echo "   النسخة $V"

echo "== 3) برنامج الديسكتوب"
mkdir -p clients
if ls "$UP"/MYTech-Desktop-Setup-*.exe >/dev/null 2>&1; then
  mv "$UP"/MYTech-Desktop-Setup-*.exe clients/
  ls -1 clients/MYTech-Desktop-Setup-* | sort -V | head -n -1 | xargs -r rm -f
else
  echo "   (مفيش ديسكتوب جديد مرفوع: القديم زي ما هو)"
fi

echo "== 4) تطبيق الموبايل"
if [ "${SKIP_APK:-0}" = 1 ]; then echo "   (اتعدّى)"; else bash build-apk.sh || echo "!! الموبايل ماتبناش (السيرفر هيتحدث عادي)"; fi

echo "== 5) السيرفر"
docker compose up -d --build
docker image prune -f >/dev/null
rm -f "$UP/mytech-src.tar.gz"
echo "اتحدث ✓  النسخة $V · البرامج: $(ls clients | tr '\n' ' ')"
