#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-up"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

cd_project
require_compose
validate_app_sources

log "garantindo bancos locais sem apagar, restaurar ou sincronizar dados..."
compose up -d "${DATABASE_SERVICES[@]}"

log "reconstruindo portal e RioB para teste..."
if [[ "${NO_CACHE:-0}" == "1" ]]; then
  compose build --no-cache "${BUILD_SERVICES[@]}"
else
  compose build "${BUILD_SERVICES[@]}"
fi
compose up -d --no-deps "${RUNTIME_SERVICES[@]}"

log "aguardando portal e RioB responderem..."
if ! wait_for_app 45 2; then
  compose logs --tail=120 "$APP_SERVICE" >&2 || true
  die "portal nao respondeu a tempo"
fi
if ! wait_for_riob 45 2; then
  compose logs --tail=120 "$RIOB_APP_SERVICE" >&2 || true
  die "RioB nao respondeu a tempo"
fi

compose ps "${DATABASE_SERVICES[@]}" "${RUNTIME_SERVICES[@]}"
log "portal e RioB prontos; bancos preservados"
