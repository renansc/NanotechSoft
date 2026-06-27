#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-restart"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

ensure_command docker
cd_project

log "reiniciando app..."
compose restart "$APP_SERVICE"

if ! wait_for_app 45 2; then
  compose logs --tail=120 "$APP_SERVICE" >&2 || true
  die "app nao respondeu apos restart"
fi

compose ps "$DB_SERVICE" "$APP_SERVICE"
