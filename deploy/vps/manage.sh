#!/usr/bin/env bash
# MYTech's own tool on the server: companies and subscriptions.  bash manage.sh <command> [options]
#   create-company --code ACME --name "..." --admin admin
#   set-subscription --company ACME --modules core,manufacturing,mfg.upvc --max-users 20 --max-branches 3 --max-devices 30 --expires 2027-12-31
#   list-subscriptions
set -euo pipefail
cd "$(dirname "$0")"
docker compose exec -w /srv/mytech api python -m tools.vendor_admin "$@"
