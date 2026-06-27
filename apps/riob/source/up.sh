#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

RIOB_DEPLOY_LOG_PREFIX="riob-up"
# shellcheck source=deploy/lib/ollama.sh
source "$REPO_DIR/deploy/lib/ollama.sh"
# shellcheck source=deploy/lib/network.sh
source "$REPO_DIR/deploy/lib/network.sh"

configure_public_access_env
ensure_public_certificate

wait_for_app_status() {
  local tries="${1:-30}"
  local delay="${2:-2}"
  local attempt
  for ((attempt=1; attempt<=tries; attempt+=1)); do
    if docker compose exec -T app python - <<'PY' >/dev/null 2>&1
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

check_ollama_connectivity() {
  docker compose exec -T app python - <<'PY'
import json
import os
import sys
import urllib.request

base = (os.environ.get("RB_AGENT_OLLAMA_URL") or "").strip().rstrip("/")
model = (os.environ.get("RB_AGENT_OLLAMA_MODEL") or "").strip()
if not base:
    raise SystemExit("RB_AGENT_OLLAMA_URL nao configurada no container app.")

def fetch_json(url: str):
    with urllib.request.urlopen(url, timeout=8) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))

errors = []
payload = None
for path in ("/api/tags", "/api/ps"):
    try:
        payload = fetch_json(base + path)
        break
    except Exception as exc:
        errors.append(f"{path}: {exc}")

if payload is None:
    raise SystemExit(
        "Nao consegui acessar o Ollama em "
        + base
        + ". Tentativas: "
        + "; ".join(errors)
    )

models = []
if isinstance(payload, dict):
    for item in payload.get("models", []) or []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("model") or "").strip()
            if name:
                models.append(name)

if model and models and model not in models:
    raise SystemExit(
        "Ollama acessivel, mas o modelo configurado nao foi encontrado: "
        + model
        + ". Modelos vistos: "
        + ", ".join(models[:10])
    )

print("Ollama OK:", base)
if model:
    print("Modelo configurado:", model)
if models:
    print("Modelos vistos:", ", ".join(models[:10]))
PY
}

check_ai_rio_route() {
  docker compose exec -T app python - <<'PY'
import json
import urllib.request

payload = {
    "message": "qual meu ip interno?",
    "history": [],
    "chat_mode": "ia",
}
request = urllib.request.Request(
    "http://127.0.0.1:8080/api/agent/chat",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=20) as response:
    data = json.loads(response.read().decode("utf-8", errors="replace"))

reply = str((data or {}).get("reply") or "").strip()
if not reply:
    raise SystemExit("A rota /api/agent/chat respondeu sem campo reply.")

print("I.A-Rio OK:", reply[:180])
PY
}

ensure_ollama_model
ensure_open_webui

echo "[riob-up] subindo app e proxy sem restaurar ou substituir o banco..."
if [[ "${NO_CACHE:-0}" == "1" ]]; then
  docker compose build --no-cache app proxy
  docker compose up -d --no-deps app proxy
else
  docker compose up -d --build --no-deps app proxy
fi

docker compose ps ollama open-webui app proxy

echo "[riob-up] aguardando app responder /api/status..."
if ! wait_for_app_status 30 2; then
  echo "[riob-up] ERRO: app nao respondeu /api/status a tempo." >&2
  exit 1
fi

./deploy/db/migrate-xml-fretes.sh

echo "[riob-up] validando acesso ao Ollama configurado..."
check_ollama_connectivity

echo "[riob-up] validando rota da I.A-Rio..."
check_ai_rio_route

validate_public_access

echo "[riob-up] app, Ollama, Qwen, Open WebUI e I.A-Rio validados."
