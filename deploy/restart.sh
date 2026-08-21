#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-restart"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

cd_project
require_compose

log "garantindo bancos antes do restart..."
compose up -d "$DB_SERVICE" "$PACS_DB_SERVICE"

log "reiniciando portal e RioB..."
compose restart "$APP_SERVICE" "$RIOB_APP_SERVICE"

if ! wait_for_app 45 2; then
  compose logs --tail=120 "$APP_SERVICE" >&2 || true
  die "app nao respondeu apos restart"
fi
if ! wait_for_riob 45 2; then
  compose logs --tail=120 "$RIOB_APP_SERVICE" >&2 || true
  die "RioB nao respondeu apos restart"
fi
refresh_and_validate_proxies

compose ps "${DATABASE_SERVICES[@]}" "${RUNTIME_SERVICES[@]}"
