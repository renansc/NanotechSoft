#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-update"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

ensure_command docker
cd_project

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
  log "atualizando codigo da branch ${BRANCH}..."
  git pull --ff-only origin "$BRANCH"
else
  log "diretorio sem repositorio Git; pulando git pull"
fi

log "recriando app sem remover volume do mysql..."
if [[ "${NO_CACHE:-0}" == "1" ]]; then
  compose build --no-cache "$APP_SERVICE"
  compose up -d --no-deps "$APP_SERVICE"
else
  compose up -d --build --no-deps "$APP_SERVICE"
fi

if ! wait_for_app 45 2; then
  compose logs --tail=120 "$APP_SERVICE" >&2 || true
  die "app nao respondeu apos update"
fi

compose ps "$DB_SERVICE" "$APP_SERVICE"
log "update concluido"
