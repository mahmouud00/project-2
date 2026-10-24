#!/bin/sh
# Wait for PostgreSQL, create roles/database, migrate, optional demo data, then serve.
set -e
echo "waiting for database..."
until python -c "import sqlalchemy as s; s.create_engine('$DATABASE_ADMIN_URL').connect().close()" 2>/dev/null; do
  sleep 2
done
python -m app.cli init-db --admin-url "$DATABASE_ADMIN_URL"
python -m app.cli migrate
if [ "$DEMO" = "1" ]; then
  python -m app.cli demo
fi
exec python -m app.cli serve
