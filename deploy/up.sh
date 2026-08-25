#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-up"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

cd_project
require_compose
validate_app_sources

log "perfil ativo: ${DEPLOY_PROFILE_ID} (${DEPLOY_MODE}), cliente ${CLIENTE_DEPLOY_ID}"
if local_database_enabled; then
  log "garantindo banco local sem apagar, restaurar ou sincronizar dados..."
  compose up -d "${DATABASE_SERVICES[@]}"
fi
ensure_riob_import_sources

log "reconstruindo os servicos de aplicacao habilitados para teste..."
if [[ "${NO_CACHE:-0}" == "1" ]]; then
  compose build --no-cache "${BUILD_SERVICES[@]}"
else
  compose build "${BUILD_SERVICES[@]}"
fi
compose up -d --no-deps "${RUNTIME_SERVICES[@]}"

log "aguardando os servicos habilitados responderem..."
if ! wait_for_app 45 2; then
  compose logs --tail=120 "$APP_SERVICE" >&2 || true
  die "portal nao respondeu a tempo"
fi
if riob_stack_enabled && ! wait_for_riob 45 2; then
  compose logs --tail=120 "$RIOB_APP_SERVICE" >&2 || true
  die "RioB nao respondeu a tempo"
fi
refresh_and_validate_proxies

compose ps "${RUNTIME_SERVICES[@]}"
log "perfil ${DEPLOY_PROFILE_ID} pronto; dados preservados"
