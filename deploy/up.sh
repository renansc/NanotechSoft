#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-up"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

ensure_command docker
cd_project

log "subindo mysql e app..."
if [[ "${NO_CACHE:-0}" == "1" ]]; then
  compose build --no-cache "$APP_SERVICE"
  compose up -d "$DB_SERVICE" "$APP_SERVICE"
else
  compose up -d --build "$DB_SERVICE" "$APP_SERVICE"
fi

log "aguardando app responder..."
if ! wait_for_app 45 2; then
  compose logs --tail=120 "$APP_SERVICE" >&2 || true
  die "app nao respondeu a tempo"
fi

compose ps "$DB_SERVICE" "$APP_SERVICE"
log "pronto em ${APP_URL}"
