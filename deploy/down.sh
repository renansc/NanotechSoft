#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-down"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

cd_project
require_compose

log "parando os servicos do perfil ${DEPLOY_PROFILE_ID} sem remover bancos, volumes ou dados..."
compose stop "${RUNTIME_SERVICES[@]}"
compose ps "${RUNTIME_SERVICES[@]}"
