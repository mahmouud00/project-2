#!/usr/bin/env bash
# Update the VPS to the newest code: backup first, then rebuild and restart (the database is migrated on start).
set -euo pipefail
cd "$(dirname "$0")"
BRANCH="${MYTECH_BRANCH:-claude/youthful-maxwell-n6mca9}"
docker compose exec -T api python -m app.cli backup --label before-update || echo "(مفيش نسخة: السيرفر مش شغال)"
git -C ../.. fetch --depth 1 origin "$BRANCH" && git -C ../.. checkout -q -B "$BRANCH" FETCH_HEAD
bash fetch-clients.sh || echo "(البرامج الجديدة ماتنزلتش: هتتنزل المرة الجاية)"
docker compose up -d --build
docker image prune -f >/dev/null
echo "اتحدث ✓  النسخة: $(docker compose exec -T api python -m app.cli version)"
