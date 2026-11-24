#!/usr/bin/env bash
# The newest desktop installer and phone app from the project's releases, into ./clients: the server offers them to
# every PC and phone («فيه نسخة جديدة») on its next start, so nobody has to send links around.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p clients
json=$(curl -fsSL "https://api.github.com/repos/mahmouud00/project-2/releases?per_page=5")
urls=$(printf '%s' "$json" | python3 -c '
import json, sys
for r in json.load(sys.stdin):
    if r.get("draft"):
        continue
    names = {a["name"]: a["browser_download_url"] for a in r.get("assets", [])}
    picks = [u for n, u in names.items() if n.startswith(("MYTech-Desktop-Setup-", "MYTech-Mobile-"))]
    if len(picks) == 2:
        print("\n".join(picks))
        break
')
[ -n "$urls" ] || { echo "مفيش نسخة برامج جديدة على GitHub"; exit 0; }
for u in $urls; do
  f="clients/$(basename "$u")"
  if [ ! -s "$f" ]; then
    echo "تنزيل $(basename "$u")"
    curl -fsSL "$u" -o "$f.part" && mv "$f.part" "$f"
  fi
done
# keep only the newest of each
for kind in MYTech-Desktop-Setup MYTech-Mobile; do
  ls -1 clients/$kind-* 2>/dev/null | sort -V | head -n -1 | xargs -r rm -f
done
echo "البرامج على السيرفر: $(ls clients | tr '\n' ' ')"
