#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-update"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

cd_project
require_compose
validate_app_sources

BRANCH="${1:-}"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [[ -z "$BRANCH" ]]; then
    BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  fi
  if [[ "${NANOTECH_UPDATE_SKIP_PULL:-0}" == "1" ]]; then
    log "git pull pulado apos reexecucao do update"
  else
    BEFORE_PULL="$(git rev-parse HEAD)"
    log "atualizando codigo da branch ${BRANCH}..."
    git pull --ff-only origin "$BRANCH"
    AFTER_PULL="$(git rev-parse HEAD)"
    if [[ "$AFTER_PULL" != "$BEFORE_PULL" && "${NANOTECH_UPDATE_REEXECED:-0}" != "1" ]]; then
      log "codigo atualizado; reexecutando script de update recem-baixado..."
      NANOTECH_UPDATE_REEXECED=1 NANOTECH_UPDATE_SKIP_PULL=1 exec "$BASH" "${BASH_SOURCE[0]}" "$BRANCH"
    fi
  fi
else
  log "diretorio sem repositorio Git; pulando git pull"
fi

ensure_riob_import_sources
stop_services_outside_profile

log "perfil ativo: ${DEPLOY_PROFILE_ID} (${DEPLOY_MODE}), cliente ${CLIENTE_DEPLOY_ID}"
log "recriando somente os servicos de aplicacao habilitados; nenhum banco sera operado..."
if [[ "${NO_CACHE:-0}" == "1" ]]; then
  compose build --no-cache "${BUILD_SERVICES[@]}"
else
  compose build "${BUILD_SERVICES[@]}"
fi
compose up -d --no-deps --remove-orphans "${RUNTIME_SERVICES[@]}"

if ! wait_for_app 45 2; then
  compose logs --tail=120 "$APP_SERVICE" >&2 || true
  die "portal nao respondeu apos update"
fi
if riob_stack_enabled && ! wait_for_riob 45 2; then
  compose logs --tail=120 "$RIOB_APP_SERVICE" >&2 || true
  die "RioB nao respondeu apos update"
fi
refresh_and_validate_proxies

compose ps "${RUNTIME_SERVICES[@]}"
log "update do perfil ${DEPLOY_PROFILE_ID} concluido, sem operacoes de banco"
