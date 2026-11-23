#!/usr/bin/env bash
# MYTech Solutions on a VPS (Ubuntu 22.04 / 24.04), run as root:
#   curl -fsSL https://raw.githubusercontent.com/mahmouud00/project-2/claude/youthful-maxwell-n6mca9/deploy/vps/install.sh -o install.sh
#   bash install.sh
# Installs Docker, gets the code into /opt/mytech, writes the secrets (.env, never in git), starts PostgreSQL +
# the server + Caddy (HTTPS by itself), and makes the MYTech account. Running it again keeps the data and secrets.
set -euo pipefail

REPO="https://github.com/mahmouud00/project-2.git"
BRANCH="${MYTECH_BRANCH:-claude/youthful-maxwell-n6mca9}"
DIR="/opt/mytech"
HERE="$DIR/deploy/vps"

[ "$(id -u)" = 0 ] || { echo "شغّله كـ root (sudo bash install.sh)"; exit 1; }

echo "== 1) Docker"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y curl git ca-certificates openssl
  # Docker's own script; on an Ubuntu too new for it, Ubuntu's own packages
  curl -fsSL https://get.docker.com | sh || apt-get install -y docker.io docker-compose-v2
fi
if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y docker-compose-v2 || apt-get install -y docker-compose-plugin
fi
systemctl enable --now docker >/dev/null 2>&1 || true
command -v git >/dev/null 2>&1 || apt-get install -y git

echo "== 2) الكود في $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch --depth 1 origin "$BRANCH" && git -C "$DIR" checkout -q -B "$BRANCH" FETCH_HEAD
else
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$DIR"
fi

echo "== 3) الإعدادات والأسرار"
cd "$HERE"
if [ ! -f .env ]; then
  read -rp "الدومين بتاع السيرفر (مثلًا app.mycompany.com): " DOMAIN
  read -rp "إيميلك (لشهادة HTTPS بس): " ACME_EMAIL
  rnd() { openssl rand -hex 24; }
  PG=$(rnd); OWNER=$(rnd); APP=$(rnd); SYS=$(rnd)
  cat > .env <<ENV
DOMAIN=$DOMAIN
ACME_EMAIL=$ACME_EMAIL
POSTGRES_PASSWORD=$PG
DATABASE_ADMIN_URL=postgresql+psycopg://postgres:$PG@db:5432/postgres
DATABASE_OWNER_URL=postgresql+psycopg://mytech_owner:$OWNER@db:5432/mytech
DATABASE_URL=postgresql+psycopg://mytech_app:$APP@db:5432/mytech
DATABASE_SYSTEM_URL=postgresql+psycopg://mytech_system:$SYS@db:5432/mytech
JWT_SECRET=$(openssl rand -hex 48)
ENV
  chmod 600 .env
  echo "اتكتبت الأسرار في $HERE/.env (احتفظ بنسخة منه في مكان آمن)."
else
  echo "الإعدادات موجودة من قبل: مش هتتغير."
fi
DOMAIN=$(grep '^DOMAIN=' .env | cut -d= -f2)

echo "== 4) الجدار الناري"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q active; then
  ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
fi

echo "== 5) التشغيل (أول مرة بتاخد كام دقيقة)"
docker compose up -d --build

echo "== 6) مستني السيرفر يشتغل"
for i in $(seq 1 90); do
  if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/system/health')" >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 3
done
[ "${ok:-}" = 1 ] || { echo "السيرفر ماشتغلش. شوف: docker compose -f $HERE/docker-compose.yml logs api"; exit 1; }

echo "== 7) حساب MYTech (لتأليف المكتبة وإدارة الشركات)"
if [ ! -f .platform-admin-done ]; then
  read -rp "اسم المستخدم لحساب MYTech [vendor]: " VU; VU=${VU:-vendor}
  docker compose exec api python -m app.cli create-platform-admin --username "$VU" && touch .platform-admin-done
fi

cat <<DONE

خلصنا ✓  السيرفر شغال على: https://$DOMAIN
  - التوثيق: https://$DOMAIN/api/docs
  - تطبيق الفنيين: https://$DOMAIN/tech

إدارة الشركات والاشتراكات (من نفس الفولدر $HERE):
  bash manage.sh create-company --code ACME --name "اسم الشركة" --admin admin
  bash manage.sh set-subscription --company ACME --modules core,manufacturing,mfg.upvc --max-users 20 --max-branches 3 --max-devices 30 --expires 2027-12-31
  bash manage.sh list-subscriptions
تحديث السيرفر لآخر نسخة:   bash update.sh
DONE
