#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-restart"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

cd_project
require_compose

log "perfil ativo: ${DEPLOY_PROFILE_ID} (${DEPLOY_MODE}), cliente ${CLIENTE_DEPLOY_ID}"
if local_database_enabled; then
  log "garantindo banco local antes do restart..."
  compose up -d "${DATABASE_SERVICES[@]}"
fi
ensure_riob_import_sources

log "reiniciando os servicos de aplicacao habilitados..."
compose restart "${BUILD_SERVICES[@]}"

if ! wait_for_app 45 2; then
  compose logs --tail=120 "$APP_SERVICE" >&2 || true
  die "app nao respondeu apos restart"
fi
if riob_stack_enabled && ! wait_for_riob 45 2; then
  compose logs --tail=120 "$RIOB_APP_SERVICE" >&2 || true
  die "RioB nao respondeu apos restart"
fi
refresh_and_validate_proxies

compose ps "${RUNTIME_SERVICES[@]}"
