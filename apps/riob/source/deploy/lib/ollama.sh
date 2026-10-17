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
