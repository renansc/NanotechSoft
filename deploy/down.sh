#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-down"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

cd_project
require_compose

log "parando app sem remover o banco..."
compose stop "$APP_SERVICE"
compose ps "$DB_SERVICE" "$APP_SERVICE"
