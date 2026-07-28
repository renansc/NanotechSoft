#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-down"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

cd_project
require_compose

log "parando portal e RioB sem remover bancos, volumes ou dados..."
compose stop "$APP_SERVICE" "$RIOB_PROXY_SERVICE" "$RIOB_APP_SERVICE"
compose ps "${DATABASE_SERVICES[@]}" "${RUNTIME_SERVICES[@]}"
