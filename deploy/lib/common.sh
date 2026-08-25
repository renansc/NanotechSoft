#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_NAME="nanotechsoft"
APP_SERVICE="app"
DB_SERVICE="mysql"
RIOB_APP_SERVICE="riob-app"
RIOB_PROXY_SERVICE="riob-proxy"
PORTAL_PROXY_SERVICE="portal-proxy"
BUILD_SERVICES=()
PROXY_SERVICES=()
RUNTIME_SERVICES=()
DATABASE_SERVICES=()
DEPLOY_PROFILE_ID=""
DEPLOY_CLIENT_ID=""
DEPLOY_MODE=""
DEPLOY_HAS_RIOB=0
DEPLOY_HAS_LOCAL_DATABASE=0
APP_URL="http://127.0.0.1:${NOTECHSOFT_APP_PORT:-5600}/login"
PORTAL_PROXY_HEALTH_URL="https://127.0.0.1:${NOTECHSOFT_HTTPS_PORT:-443}/healthz"
RIOB_PROXY_STATUS_URL="https://127.0.0.1:${RB_HTTPS_PORT:-8899}/api/status"
RIOB_PROXY_STARTUP_TRIES=120
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

configure_deploy_profile() {
  local py profile_id profiles_file output key value
  py="$(python_cmd)" || die "python nao encontrado para carregar o perfil de deploy"
  profile_id="${NANOTECH_DEPLOY_PROFILE:-${CLIENTE_DEPLOY_ID:-rio-branco}}"
  profiles_file="${NANOTECH_DEPLOY_PROFILES_FILE:-$PROJECT_DIR/deploy/profiles.json}"

  output="$($py - "$profiles_file" "$profile_id" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
requested = re.sub(r"[^a-z0-9]+", "-", sys.argv[2].strip().lower()).strip("-")
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"ERRO=perfil de deploy invalido em {path}: {exc}")
    raise SystemExit(2)

profiles = payload.get("profiles") or []
profile = next((item for item in profiles if str(item.get("id") or "").strip() == requested), None)
if not profile:
    print(f"ERRO=perfil de deploy nao encontrado: {requested}")
    raise SystemExit(2)

mode = str(profile.get("mode") or "local").strip()
if mode not in {"local", "cloud-readonly"}:
    print(f"ERRO=modo de deploy invalido no perfil {requested}: {mode}")
    raise SystemExit(2)

print(f"PROFILE_ID={requested}")
print(f"CLIENT_ID={str(profile.get('clientId') or requested).strip()}")
print(f"MODE={mode}")
print(f"RIOB={1 if profile.get('riobStack') is True else 0}")
print(f"LOCAL_DB={1 if profile.get('localDatabase') is True else 0}")
PY
  )" || die "${output#ERRO=}"

  while IFS='=' read -r key value; do
    case "$key" in
      PROFILE_ID) DEPLOY_PROFILE_ID="$value" ;;
      CLIENT_ID) DEPLOY_CLIENT_ID="$value" ;;
      MODE) DEPLOY_MODE="$value" ;;
      RIOB) DEPLOY_HAS_RIOB="$value" ;;
      LOCAL_DB) DEPLOY_HAS_LOCAL_DATABASE="$value" ;;
      ERRO) die "$value" ;;
    esac
  done <<<"$output"

  if [[ -n "${CLIENTE_DEPLOY_ID:-}" && "$CLIENTE_DEPLOY_ID" != "$DEPLOY_CLIENT_ID" && "${NANOTECH_ALLOW_PROFILE_CLIENT_OVERRIDE:-0}" != "1" ]]; then
    die "CLIENTE_DEPLOY_ID=$CLIENTE_DEPLOY_ID diverge do perfil $DEPLOY_PROFILE_ID ($DEPLOY_CLIENT_ID)"
  fi

  export CLIENTE_DEPLOY_ID="${CLIENTE_DEPLOY_ID:-$DEPLOY_CLIENT_ID}"
  export NS_DEPLOY_MODE="${NS_DEPLOY_MODE:-$DEPLOY_MODE}"

  BUILD_SERVICES=("$APP_SERVICE")
  PROXY_SERVICES=("$PORTAL_PROXY_SERVICE")
  RUNTIME_SERVICES=("$APP_SERVICE" "$PORTAL_PROXY_SERVICE")
  if [[ "$DEPLOY_HAS_LOCAL_DATABASE" == "1" ]]; then
    DATABASE_SERVICES=("$DB_SERVICE")
  fi
  if [[ "$DEPLOY_HAS_RIOB" == "1" ]]; then
    BUILD_SERVICES+=("$RIOB_APP_SERVICE")
    PROXY_SERVICES+=("$RIOB_PROXY_SERVICE")
    RUNTIME_SERVICES=("$RIOB_APP_SERVICE" "$RIOB_PROXY_SERVICE" "$APP_SERVICE" "$PORTAL_PROXY_SERVICE")
  fi
}

configure_deploy_profile

riob_stack_enabled() {
  [[ "$DEPLOY_HAS_RIOB" == "1" ]]
}

local_database_enabled() {
  [[ "$DEPLOY_HAS_LOCAL_DATABASE" == "1" ]]
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

ensure_riob_import_sources() {
  local py compose_json source
  local -a sources=()

  if ! riob_stack_enabled; then
    return 0
  fi

  py="$(python_cmd)" || die "python nao encontrado para validar as pastas de importacao do RioB"
  if compose_json="$(compose config --format json 2>/dev/null)"; then
    while IFS= read -r source; do
      [[ -n "$source" ]] && sources+=("$source")
    done < <(
      printf '%s' "$compose_json" | "$py" -c '
import json, sys
config = json.load(sys.stdin)
targets = {"/imports/vendas-diario/txt", "/imports/vendas-diario/pdf"}
for volume in config.get("services", {}).get("riob-app", {}).get("volumes", []):
    if isinstance(volume, dict) and volume.get("type") == "bind" and volume.get("target") in targets:
        print(volume.get("source") or "")
'
    )
  fi

  if [[ "${#sources[@]}" -eq 0 ]]; then
    sources=(
      "${RB_VENDAS_DIARIO_TXT_HOST_DIR:-/media/serverwin/CARGAS/CargasTxt}"
      "${RB_VENDAS_DIARIO_PDF_HOST_DIR:-/media/serverwin/CARGAS/VendasDiarioPdfs}"
    )
  fi

  log "validando pastas de importacao do RioB antes de operar os containers..."
  for source in "${sources[@]}"; do
    if [[ ! -d "$source" ]]; then
      die "pasta de importacao indisponivel: $source. Verifique o compartilhamento do host antes de reiniciar o RioB."
    fi
  done
}

validate_client_contracts() {
  local py
  py="$(python_cmd)" || die "python nao encontrado para validar clientes"

  "$py" - <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path.cwd().resolve()
contracts_path = root / "clientes-modulos.json"
apps_dir = root / "apps"
errors = []

def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")

if not contracts_path.exists():
    print("- clientes-modulos.json nao encontrado", file=sys.stderr)
    sys.exit(1)

try:
    data = json.loads(contracts_path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"- clientes-modulos.json invalido ({exc})", file=sys.stderr)
    sys.exit(1)

clients = data.get("clients") or data.get("clientes") or []
if not isinstance(clients, list) or not clients:
    errors.append("clientes-modulos.json deve conter clients com pelo menos um cliente")

manifest_keys = set()
for manifest in sorted(apps_dir.glob("*/app.json")):
    try:
        item = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        continue
    manifest_keys.add(str(item.get("app_key") or manifest.parent.name).strip())

seen_clients = set()
for index, client in enumerate(clients if isinstance(clients, list) else []):
    if not isinstance(client, dict):
        errors.append(f"clients[{index}] deve ser objeto")
        continue
    client_id = slug(client.get("id") or client.get("nome"))
    if not client_id:
        errors.append(f"clients[{index}] sem id/nome valido")
        continue
    if client_id in seen_clients:
        errors.append(f"cliente duplicado: {client_id}")
    seen_clients.add(client_id)

    modules = client.get("modules") or client.get("modulos") or []
    if client.get("allModules") is True:
        continue
    if not isinstance(modules, list):
        errors.append(f"{client_id}: modules deve ser lista")
        continue
    seen_modules = set()
    for module in modules:
        module_id = slug(module if isinstance(module, str) else module.get("slug") or module.get("id") or module.get("nome"))
        status = "" if isinstance(module, str) else str(module.get("status") or "contratado").strip()
        if not module_id:
            errors.append(f"{client_id}: modulo sem slug")
            continue
        if module_id in seen_modules:
            errors.append(f"{client_id}: modulo duplicado {module_id}")
        seen_modules.add(module_id)
        has_external_target = bool(
            isinstance(module, dict)
            and (str(module.get("href") or "").strip() or str(module.get("hrefEnv") or "").strip())
        )
        if module_id not in manifest_keys and not (
            status == "importar" or (status == "externo" and has_external_target)
        ):
            errors.append(
                f"{client_id}: modulo {module_id} nao existe em apps/*/app.json "
                "e nao possui destino externo valido"
            )

profiles_path = root / "deploy" / "profiles.json"
try:
    profiles_payload = json.loads(profiles_path.read_text(encoding="utf-8"))
except Exception as exc:
    errors.append(f"deploy/profiles.json invalido ({exc})")
    profiles_payload = {}

profiles = profiles_payload.get("profiles") or []
seen_profiles = set()
for index, profile in enumerate(profiles if isinstance(profiles, list) else []):
    if not isinstance(profile, dict):
        errors.append(f"profiles[{index}] deve ser objeto")
        continue
    profile_id = slug(profile.get("id"))
    client_id = slug(profile.get("clientId") or profile_id)
    if not profile_id or profile_id in seen_profiles:
        errors.append(f"perfil de deploy ausente ou duplicado: {profile_id or index}")
    seen_profiles.add(profile_id)
    if client_id not in seen_clients:
        errors.append(f"perfil {profile_id}: cliente inexistente {client_id}")
    if profile.get("mode") not in {"local", "cloud-readonly"}:
        errors.append(f"perfil {profile_id}: mode invalido")
    if profile.get("mode") == "cloud-readonly" and (
        profile.get("localDatabase") is not False or profile.get("riobStack") is not False
    ):
        errors.append(f"perfil {profile_id}: nuvem nao pode iniciar banco local ou RioB")

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
except ModuleNotFoundError as exc:
    portal = None
    print(
        f"- aviso: importacao de app.py pulada porque falta dependencia local ({exc}). "
        "Instale requirements.txt para validar rotas/temas do portal nesta etapa.",
        file=sys.stderr,
    )
except Exception as exc:
    print(f"- nao foi possivel importar app.py para validar o portal: {exc}", file=sys.stderr)
    sys.exit(1)

manifest_keys = set()
menu_sections = set(getattr(portal, "MENU_SECTIONS", (
    "dashboards",
    "cadastros",
    "ponto",
    "automacao",
    "workflow",
    "compras",
    "estoque",
    "financeiro",
    "relatorios",
    "import_export",
))) if portal else {
    "dashboards",
    "cadastros",
    "ponto",
    "automacao",
    "workflow",
    "compras",
    "estoque",
    "financeiro",
    "relatorios",
    "import_export",
}
financeiro_views = set(getattr(portal, "FINANCEIRO_VIEWS", (
    "dashboard",
    "lancamentos",
    "contas",
    "categorias",
    "cadastros",
    "importar",
    "conciliacao",
    "compras",
    "pagar",
    "receber",
    "config",
))) if portal else {
    "dashboard",
    "lancamentos",
    "contas",
    "categorias",
    "cadastros",
    "importar",
    "conciliacao",
    "compras",
    "pagar",
    "receber",
    "config",
}

for manifest in sorted((root / "apps").glob("*/app.json")):
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{manifest.relative_to(root)}: JSON invalido ({exc})")
        continue

    app_key = str(data.get("app_key") or manifest.parent.name).strip()
    manifest_keys.add(app_key)

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
                if section not in menu_sections:
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
                    if view not in financeiro_views:
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

if portal is not None:
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
            "riob-remoto": portal.rewrite_riob_html(sample).decode("utf-8"),
        }
        for app_key, html in standalone_checks.items():
            assert_theme(app_key, html)

        for app_key in sorted(portal.LOCAL_RIOB_APPS):
            html = portal.rewrite_local_riob_text(sample, app_key, apply_theme=True).decode("utf-8")
            assert_theme(app_key, html)

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

wait_for_riob() {
  local tries="${1:-45}"
  local delay="${2:-2}"
  local attempt

  if ! riob_stack_enabled; then
    return 0
  fi

  for ((attempt=1; attempt<=tries; attempt+=1)); do
    if compose exec -T "$RIOB_APP_SERVICE" python - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("http://127.0.0.1:8080/api/status", timeout=5).read()
PY
    then
      return 0
    fi
    sleep "$delay"
  done

  return 1
}

wait_for_proxy_url() {
  local url="$1"
  local tries="${2:-30}"
  local delay="${3:-2}"
  local attempt

  command -v curl >/dev/null 2>&1 || return 1
  for ((attempt=1; attempt<=tries; attempt+=1)); do
    if curl --silent --show-error --fail --insecure --max-time 10 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done

  return 1
}

refresh_and_validate_proxies() {
  log "reiniciando proxies para atualizar os enderecos internos Docker..."
  compose restart "${PROXY_SERVICES[@]}"

  if ! wait_for_proxy_url "$PORTAL_PROXY_HEALTH_URL" 30 2; then
    compose logs --tail=120 "$PORTAL_PROXY_SERVICE" >&2 || true
    die "portal nao respondeu pelo proxy apos atualizar os enderecos internos"
  fi
  if riob_stack_enabled; then
    if ! wait_for_proxy_url "$RIOB_PROXY_STATUS_URL" "$RIOB_PROXY_STARTUP_TRIES" 2; then
      compose logs --tail=120 "$RIOB_PROXY_SERVICE" >&2 || true
      die "RioB nao respondeu pelo proxy apos atualizar os enderecos internos"
    fi
  fi
}
