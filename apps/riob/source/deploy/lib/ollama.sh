#!/usr/bin/env bash

env_file_value() {
  local key="$1"
  awk -F= -v key="$key" '
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      sub(/^[^=]*=/, "", $0)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
      gsub(/^"|"$/, "", $0)
      print $0
      exit
    }
  ' .env 2>/dev/null || true
}

configure_ollama_deploy_env() {
  local managed model prefix
  prefix="${RIOB_DEPLOY_LOG_PREFIX:-riob}"
  managed="${RB_MANAGED_OLLAMA:-$(env_file_value RB_MANAGED_OLLAMA)}"
  managed="${managed:-1}"
  if [[ "$managed" != "0" ]]; then
    model="${RB_MANAGED_OLLAMA_MODEL:-$(env_file_value RB_MANAGED_OLLAMA_MODEL)}"
    model="${model:-qwen2.5:3b}"
  else
    model="${RB_AGENT_OLLAMA_MODEL:-$(env_file_value RB_AGENT_OLLAMA_MODEL)}"
    model="${model:-qwen2.5:3b}"
  fi

  export RB_MANAGED_OLLAMA_MODEL="$model"
  export RB_AGENT_OLLAMA_MODEL="$model"
  if [[ "$managed" != "0" ]]; then
    export RB_AGENT_OLLAMA_URL="http://ollama:11434"
  fi

  echo "[${prefix}] Ollama gerenciado: ${managed}"
  echo "[${prefix}] Modelo Ollama: ${RB_AGENT_OLLAMA_MODEL}"
  echo "[${prefix}] URL Ollama do app: ${RB_AGENT_OLLAMA_URL:-$(env_file_value RB_AGENT_OLLAMA_URL)}"
}

ensure_ollama_model() {
  local prefix managed
  prefix="${RIOB_DEPLOY_LOG_PREFIX:-riob}"
  configure_ollama_deploy_env
  managed="${RB_MANAGED_OLLAMA:-$(env_file_value RB_MANAGED_OLLAMA)}"
  managed="${managed:-1}"
  if [[ "$managed" == "0" ]]; then
    echo "[${prefix}] RB_MANAGED_OLLAMA=0; usando Ollama externo configurado."
    return 0
  fi

  echo "[${prefix}] subindo Ollama e garantindo modelo ${RB_AGENT_OLLAMA_MODEL}..."
  docker compose up -d ollama
  docker compose run --rm ollama-model-init
}

wait_for_compose_service_health() {
  local service="$1"
  local tries="${2:-90}"
  local delay="${3:-2}"
  local container_id status attempt

  for ((attempt=1; attempt<=tries; attempt+=1)); do
    container_id="$(docker compose ps -q "$service" 2>/dev/null || true)"
    if [[ -n "$container_id" ]]; then
      status="$(docker inspect --format '{{if .Config.Healthcheck}}{{if .State.Health}}{{.State.Health.Status}}{{else}}starting{{end}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
      if [[ "$status" == "healthy" || "$status" == "running" ]]; then
        return 0
      fi
    fi
    sleep "$delay"
  done

  return 1
}

validate_open_webui_model() {
  docker compose exec -T open-webui python - <<'PY'
import json
import os
import urllib.request

base = (os.environ.get("OLLAMA_BASE_URL") or "").strip().rstrip("/")
model = (os.environ.get("DEFAULT_MODELS") or "").strip()
if not base:
    raise SystemExit("OLLAMA_BASE_URL nao configurada no Open WebUI.")
if not model:
    raise SystemExit("DEFAULT_MODELS nao configurado no Open WebUI.")

with urllib.request.urlopen(base + "/api/tags", timeout=10) as response:
    payload = json.loads(response.read().decode("utf-8", errors="replace"))

models = []
for item in payload.get("models", []) or []:
    if isinstance(item, dict):
        name = str(item.get("name") or item.get("model") or "").strip()
        if name:
            models.append(name)

if model not in models:
    raise SystemExit(
        "Open WebUI acessou o Ollama, mas nao encontrou o modelo "
        + model
        + ". Modelos vistos: "
        + ", ".join(models[:10])
    )

print("Open WebUI OK:", base)
print("Modelo padrao:", model)
PY
}

ensure_open_webui() {
  local prefix
  prefix="${RIOB_DEPLOY_LOG_PREFIX:-riob}"

  echo "[${prefix}] subindo Open WebUI com o modelo ${RB_AGENT_OLLAMA_MODEL:-qwen2.5:3b}..."
  if [[ "${NO_CACHE:-0}" == "1" ]]; then
    docker compose build --no-cache open-webui
    docker compose up -d --no-deps open-webui
  else
    docker compose up -d --build --no-deps open-webui
  fi

  if ! wait_for_compose_service_health open-webui 180 2; then
    echo "[${prefix}] ERRO: Open WebUI nao ficou saudavel a tempo." >&2
    docker compose logs --tail=120 open-webui >&2 || true
    return 1
  fi

  validate_open_webui_model
}
