#!/usr/bin/env bash
# Update the VPS to the newest code from GitHub: backup first, then rebuild and restart (the database is migrated
# on start). Without GitHub: tools/release/deploy.ps1 on your PC (it runs update-from-upload.sh here).
set -euo pipefail
cd "$(dirname "$0")"
git -C ../.. remote get-url origin >/dev/null 2>&1 || { echo "مفيش GitHub: حدّث من جهازك بـ tools/release/deploy.ps1"; exit 1; }
BRANCH="${MYTECH_BRANCH:-claude/youthful-maxwell-n6mca9}"
docker compose exec -T api python -m app.cli backup --label before-update || echo "(مفيش نسخة: السيرفر مش شغال)"
git -C ../.. fetch --depth 1 origin "$BRANCH" && git -C ../.. checkout -q -B "$BRANCH" FETCH_HEAD
bash fetch-clients.sh || echo "(البرامج الجديدة ماتنزلتش: هتتنزل المرة الجاية)"
docker compose up -d --build
docker image prune -f >/dev/null
echo "اتحدث ✓  النسخة: $(docker compose exec -T api python -m app.cli version)"
