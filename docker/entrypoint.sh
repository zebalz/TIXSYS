#!/bin/sh
# Runs every time the app container starts: waits for the database,
# applies database updates, makes sure starter settings exist, then starts the app.
set -e

echo "Waiting for the database..."
python - <<'PY'
import os, sys, time
import psycopg

for attempt in range(60):
    try:
        psycopg.connect(
            host=os.environ.get("POSTGRES_HOST", "db"),
            port=os.environ.get("POSTGRES_PORT", "5432"),
            dbname=os.environ.get("POSTGRES_DB", "tixsys"),
            user=os.environ.get("POSTGRES_USER", "tixsys"),
            password=os.environ.get("POSTGRES_PASSWORD", ""),
            connect_timeout=3,
        ).close()
        sys.exit(0)
    except Exception as exc:
        time.sleep(2)
print("Database didn't come up in time.", file=sys.stderr)
sys.exit(1)
PY

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py bootstrap

exec "$@"
