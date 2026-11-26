#!/usr/bin/env bash
# Build the phone app (APK) here on the VPS and put it in ./clients, where every phone finds «فيه نسخة جديدة».
# It is always signed with the SAME key (/opt/mytech-keys): a phone installs each new version over the old one.
# The key is made once, the first time. KEEP A COPY OF /opt/mytech-keys: without it no update installs on the phones.
#   bash build-apk.sh            (the version is the one in /opt/mytech/VERSION)
set -euo pipefail
cd "$(dirname "$0")"
HERE=$(pwd)
ROOT=$(cd ../.. && pwd)
KEYS=/opt/mytech-keys
WORK=/var/lib/mytech-build/src
IMAGE=mytech-android-build

V=$(tr -d '[:space:]' < "$ROOT/VERSION")
BUILD=${V##*.}
CODE=$((100000 + BUILD))                  # Android's own number: always higher than the version before
echo "== بناء تطبيق الموبايل $V"

docker build -q -t "$IMAGE" android >/dev/null

# the signing key: made once, then the same key for ever
mkdir -p "$KEYS" && chmod 700 "$KEYS"
if [ ! -s "$KEYS/mytech-release.jks" ]; then
  echo "== أول مرة: بعمل مفتاح التوقيع الثابت في $KEYS (احتفظ بنسخة منه!)"
  openssl rand -hex 20 > "$KEYS/password.txt" && chmod 600 "$KEYS/password.txt"
  docker run --rm -v "$KEYS":/keys "$IMAGE" keytool -genkeypair -keystore /keys/mytech-release.jks -alias mytech \
    -keyalg RSA -keysize 2048 -validity 15000 -storepass "$(cat "$KEYS/password.txt")" \
    -keypass "$(cat "$KEYS/password.txt")" -dname "CN=MYTech Solutions, O=MYTech Solutions, C=EG"
  chmod 600 "$KEYS/mytech-release.jks"
fi

# a clean copy of the code to build from (never the running server's folder)
mkdir -p "$WORK"
rsync -a --delete --exclude '.git/' --exclude 'deploy/vps/.env' --exclude 'deploy/vps/clients/' \
  --exclude 'node_modules/' --exclude 'desktop/src-tauri/target/' "$ROOT"/ "$WORK"/

docker run --rm -v "$WORK":/src -v "$KEYS":/keys:ro \
  -v mytech-gradle:/root/.gradle -v mytech-cargo-registry:/opt/cargo/registry \
  -v mytech-android-target:/src/desktop/src-tauri/target -v mytech-npm:/root/.npm \
  -e CODE="$CODE" "$IMAGE" bash -euc '
    cd /src/desktop
    npm ci --no-audit --no-fund
    printf "keyAlias=mytech\npassword=%s\nstoreFile=/keys/mytech-release.jks\n" "$(cat /keys/password.txt)" \
      > src-tauri/gen/android/keystore.properties
    npx tauri android build --apk --ci --target aarch64 --target armv7 \
      --config "{\"bundle\":{\"android\":{\"versionCode\":$CODE}}}"
    rm -f src-tauri/gen/android/keystore.properties'

APK=$(find "$WORK/desktop/src-tauri/gen/android/app/build/outputs/apk" -name '*release*.apk' | head -n 1)
[ -n "$APK" ] || { echo "التطبيق ماتبناش"; exit 1; }
mkdir -p "$HERE/clients"
cp "$APK" "$HERE/clients/MYTech-Mobile-$V.apk"
ls -1 "$HERE"/clients/MYTech-Mobile-* 2>/dev/null | sort -V | head -n -1 | xargs -r rm -f
echo "✓ تطبيق الموبايل $V جاهز (موقّع بالمفتاح الثابت)"
