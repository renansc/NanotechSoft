#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_NAME="nanotechsoft"
APP_SERVICE="app"
DB_SERVICE="mysql"
APP_URL="http://127.0.0.1:${NOTECHSOFT_APP_PORT:-5600}/login"
COMPOSE_CMD=()

log() {
  printf '[%s] %s\n' "${LOG_PREFIX:-deploy}" "$*"
}

die() {
  printf '[%s] ERRO: %s\n' "${LOG_PREFIX:-deploy}" "$*" >&2
  exit 1
}

ensure_command() {
  command -v "$1" >/dev/null 2>&1 || die "$1 nao encontrado"
}

detect_compose() {
  if [[ "${#COMPOSE_CMD[@]}" -gt 0 ]]; then
    return 0
  fi

  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
    return 0
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
    return 0
  fi

  if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(podman compose)
    return 0
  fi

  return 1
}

require_compose() {
  if detect_compose; then
    return 0
  fi

  die "nenhum Docker Compose encontrado. Instale Docker com o plugin compose, docker-compose ou podman compose; se estiver em VS Code/Codium Flatpak, execute fora do sandbox ou exponha o Docker CLI."
}

compose() {
  require_compose
  "${COMPOSE_CMD[@]}" "$@"
}

cd_project() {
  cd "$PROJECT_DIR"
}

python_cmd() {
  if [[ -x ".venv/bin/python" ]]; then
    printf '%s\n' ".venv/bin/python"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
    return 0
  fi

  return 1
}

validate_app_sources() {
  local py
  py="$(python_cmd)" || die "python nao encontrado para validar os apps"

  "$py" - <<'PY'
import json
import sys
from pathlib import Path

root = Path.cwd().resolve()
apps_dir = root / "apps"
errors = []

if not apps_dir.exists():
    errors.append("diretorio apps/ nao existe")
else:
    for manifest in sorted(apps_dir.glob("*/app.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{manifest.relative_to(root)}: JSON invalido ({exc})")
            continue

        app_key = data.get("app_key") or manifest.parent.name
        source_dir = str(data.get("source_dir") or "").strip()
        if not source_dir:
            errors.append(f"{manifest.relative_to(root)}: source_dir ausente")
            continue

        source_path = Path(source_dir)
        if source_path.is_absolute():
            errors.append(f"{app_key}: source_dir deve ser relativo ao repositorio: {source_dir}")
            continue

        resolved = (root / source_path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            errors.append(f"{app_key}: source_dir aponta para fora do repositorio: {source_dir}")
            continue

        if not resolved.exists():
            errors.append(f"{app_key}: source_dir nao existe: {source_dir}")

if errors:
    for item in errors:
        print(f"- {item}", file=sys.stderr)
    sys.exit(1)
PY
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
