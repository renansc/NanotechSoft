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

validate_portal_integrations() {
  local py
  py="$(python_cmd)" || die "python nao encontrado para validar integracoes do portal"

  "$py" - <<'PY'
import importlib
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

root = Path.cwd().resolve()
errors = []

try:
    portal = importlib.import_module("app")
except Exception as exc:
    print(f"- nao foi possivel importar app.py para validar o portal: {exc}", file=sys.stderr)
    sys.exit(1)

allowed = portal.allowed_app_keys()
manifest_keys = set()

for manifest in sorted((root / "apps").glob("*/app.json")):
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{manifest.relative_to(root)}: JSON invalido ({exc})")
        continue

    app_key = str(data.get("app_key") or manifest.parent.name).strip()
    manifest_keys.add(app_key)
    if allowed is not None and app_key not in allowed:
        errors.append(f"{app_key}: app ativo fora de apps_liberados.txt")

    for field in ("url", "standalone_url"):
        url = str(data.get(field) or "").strip()
        if not url:
            errors.append(f"{app_key}: {field} vazio")
        elif not url.startswith("/"):
            errors.append(f"{app_key}: {field} deve apontar para rota interna: {url}")

    for group_name in ("menu_groups", "config_groups"):
        groups = data.get(group_name) or {}
        if not isinstance(groups, dict):
            errors.append(f"{app_key}: {group_name} deve ser objeto")
            continue
        if group_name == "menu_groups":
            for section in groups:
                if section not in portal.MENU_SECTIONS:
                    errors.append(f"{app_key}: secao de menu desconhecida: {section}")
        for section, items in groups.items():
            if not isinstance(items, list):
                errors.append(f"{app_key}: {group_name}.{section} deve ser lista")
                continue
            for index, item in enumerate(items):
                url = item.get("url") if isinstance(item, dict) else ""
                if not url:
                    errors.append(f"{app_key}: {group_name}.{section}[{index}] sem url")
                    continue
                parsed = urlparse(url)
                if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
                    errors.append(f"{app_key}: link de menu nao interno: {url}")
                if parsed.path.startswith("/apps/financeiro"):
                    view = parse_qs(parsed.query).get("view", ["dashboard"])[0]
                    if view not in portal.FINANCEIRO_VIEWS:
                        errors.append(f"{app_key}: view financeira invalida em {url}")
                if parsed.path.startswith("/workflow/"):
                    target = parsed.path.split("/", 2)[2]
                    if target not in manifest_keys and not (root / "apps" / target / "app.json").exists():
                        errors.append(f"{app_key}: workflow aponta para app inexistente: {url}")

    cards = data.get("workflow_cards") or []
    if not isinstance(cards, list):
        errors.append(f"{app_key}: workflow_cards deve ser lista")
    else:
        for index, item in enumerate(cards):
            if not isinstance(item, dict) or not item.get("url"):
                errors.append(f"{app_key}: workflow_cards[{index}] sem url")

sample = b'<!doctype html><html><head><title>x</title></head><body class="legacy"><a href="/api/test">x</a><script src="/app.js"></script></body></html>'

def assert_theme(app_key, html):
    if "window.NOTECHSOFT_THEME" not in html or "theme-rio_branco" not in html:
        errors.append(f"{app_key}: janela externa/original sem tema NanotechSoft")

with portal.app.test_request_context("/"):
    standalone_checks = {
        "automacao": portal.apply_standalone_theme(portal.rewrite_automacao_html(sample, prefix="/apps/automacao/original").decode("utf-8")),
        "financeiro": portal.apply_standalone_theme(sample.decode("utf-8")),
        "nanoponto": portal.rewrite_nanoponto_html(sample, integrated=False),
        "zap": portal.rewrite_zap_document(sample, integrated=False),
        "nanostore": portal.rewrite_nanostore_html(sample, integrated=False),
        "gpsmusical": portal.rewrite_static_app_html(sample.decode("utf-8"), "gpsmusical", integrated=False),
        "bpa": portal.rewrite_static_app_html(sample.decode("utf-8"), "bpa", integrated=False),
        "tatoo": portal.rewrite_static_app_html(sample.decode("utf-8"), "tatoo", integrated=False),
        "riob-remoto": portal.rewrite_riob_html(sample).decode("utf-8"),
    }
    for app_key, html in standalone_checks.items():
        assert_theme(app_key, html)

    for app_key in sorted(portal.LOCAL_RIOB_APPS):
        html = portal.rewrite_local_riob_text(sample, app_key, apply_theme=True).decode("utf-8")
        assert_theme(app_key, html)

    if "UI_showTab" not in standalone_checks["gpsmusical"]:
        errors.append("gpsmusical: ponte de hash para abas nao encontrada")
    if "activateFromHash" not in standalone_checks["nanostore"]:
        errors.append("nanostore: ponte de hash para visoes nao encontrada")
    if "openFromHash" not in standalone_checks["riob-remoto"]:
        errors.append("riob: ponte de hash para modulos nao encontrada")

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
