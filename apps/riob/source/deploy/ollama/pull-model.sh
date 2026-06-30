#!/bin/sh
set -eu

host="${OLLAMA_HOST:-http://ollama:11434}"
model="${RB_AGENT_OLLAMA_MODEL:-${OLLAMA_MODEL:-qwen2.5:3b}}"
remove_models="${RB_OLLAMA_REMOVE_MODELS:-qwen2.5:7b}"
tries="${RB_OLLAMA_PULL_WAIT_TRIES:-60}"
delay="${RB_OLLAMA_PULL_WAIT_DELAY:-2}"

if [ -z "$model" ]; then
  echo "[ollama-bootstrap] RB_AGENT_OLLAMA_MODEL nao configurado." >&2
  exit 1
fi

export OLLAMA_HOST="$host"

echo "[ollama-bootstrap] aguardando Ollama em ${OLLAMA_HOST}..."
i=1
while [ "$i" -le "$tries" ]; do
  if ollama list >/dev/null 2>&1; then
    break
  fi
  sleep "$delay"
  i=$((i + 1))
done

if ! ollama list >/dev/null 2>&1; then
  echo "[ollama-bootstrap] Ollama nao respondeu em ${OLLAMA_HOST}." >&2
  exit 1
fi

echo "[ollama-bootstrap] garantindo modelo ${model}..."
ollama pull "$model"

if ! ollama show "$model" >/dev/null 2>&1; then
  echo "[ollama-bootstrap] modelo ${model} nao ficou disponivel apos o pull." >&2
  exit 1
fi

old_ifs="$IFS"
IFS=","
for old_model in $remove_models; do
  old_model="$(printf '%s' "$old_model" | xargs)"
  if [ -z "$old_model" ] || [ "$old_model" = "$model" ]; then
    continue
  fi
  if ollama show "$old_model" >/dev/null 2>&1; then
    echo "[ollama-bootstrap] removendo modelo antigo ${old_model}..."
    ollama rm "$old_model"
  fi
done
IFS="$old_ifs"

echo "[ollama-bootstrap] modelo ${model} instalado e validado."
