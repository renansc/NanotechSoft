#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_NAME="nanotechsoft"
APP_SERVICE="app"
DB_SERVICE="mysql"
APP_URL="http://127.0.0.1:${NOTECHSOFT_APP_PORT:-5600}/login"

log() {
  printf '[%s] %s\n' "${LOG_PREFIX:-deploy}" "$*"
}

die() {
  printf '[%s] ERRO: %s\n' "${LOG_PREFIX:-deploy}" "$*" >&2
  exit 1
}

compose() {
  docker compose "$@"
}

ensure_command() {
  command -v "$1" >/dev/null 2>&1 || die "$1 nao encontrado"
}

cd_project() {
  cd "$PROJECT_DIR"
}

wait_for_app() {
  local tries="${1:-45}"
  local delay="${2:-2}"
  local attempt

  for ((attempt=1; attempt<=tries; attempt+=1)); do
    if compose exec -T "$APP_SERVICE" python - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("http://127.0.0.1:5600/login", timeout=5).read()
PY
    then
      return 0
    fi
    sleep "$delay"
  done

  return 1
}
