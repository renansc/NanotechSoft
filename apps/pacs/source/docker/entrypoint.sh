#!/bin/sh
set -eu

python3 /app/scripts/wait_for_db.py

if [ "${AUTO_BOOTSTRAP_SCHEMA:-1}" = "1" ]; then
  python3 /app/scripts/bootstrap_db.py
else
  echo "AUTO_BOOTSTRAP_SCHEMA=0; pulando bootstrap do banco."
fi

MODE="${1:-web}"

if [ "$MODE" = "web" ]; then
  WEB_HOST="${APP_HOST:-0.0.0.0}"
  WEB_PORT="${PORT:-}"
  if [ -z "$WEB_PORT" ]; then
    WEB_PORT="${APP_PORT:-5020}"
  fi
  export PORT="$WEB_PORT"
  export APP_PORT="${APP_PORT:-$WEB_PORT}"
  echo "Starting web service on ${WEB_HOST}:${WEB_PORT}"
  exec gunicorn -b "${WEB_HOST}:${WEB_PORT}" app:app
fi

if [ "$MODE" = "worklist" ]; then
  exec python3 -m raiox_pacs.worklist_server
fi

if [ "$MODE" = "dicom" ]; then
  exec python3 -m raiox_pacs.dicom_server
fi

exec "$@"
