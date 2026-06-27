#!/usr/bin/env bash
set -euo pipefail

OLLAMA_URL="${OLLAMA_URL:-${RB_AGENT_OLLAMA_URL:-http://localhost:11434}}"
OLLAMA_URL="${OLLAMA_URL%/}"
OLLAMA_URL="${OLLAMA_URL%/api}"
MODEL="${OLLAMA_MODEL:-${RB_AGENT_OLLAMA_MODEL:-}}"
PROMPT="${*:-}"

usage() {
  cat <<'EOF'
Usage:
  ollama_watch.sh <prompt...>
  ow <prompt...>
  OLLAMA_MODEL=llama3.1:8b ow <prompt...>
  RB_AGENT_OLLAMA_URL=http://127.0.0.1:11434 ow "prompt"

Environment:
  OLLAMA_URL / RB_AGENT_OLLAMA_URL  Ollama base URL, default: http://127.0.0.1:11434
  OLLAMA_MODEL / RB_AGENT_OLLAMA_MODEL  Model name, auto-detects the first chat model if unset

Example:
  OLLAMA_URL=http://localhost:11434 ./tools/ollama_watch.sh "Explique em uma frase o que esta acontecendo"
EOF
}

if [[ -z "${PROMPT}" ]]; then
  usage >&2
  exit 1
fi

for cmd in curl jq date awk; do
  command -v "${cmd}" >/dev/null 2>&1 || {
    echo "Missing dependency: ${cmd}" >&2
    exit 1
  }
done

preflight_url="$OLLAMA_URL/api/ps"
http_code="$(
  curl -sS -o /dev/null -w '%{http_code}' "${preflight_url}" 2>/dev/null || true
)"
if [[ "${http_code}" == "404" ]]; then
  echo "404 em ${preflight_url}" >&2
  echo "Use OLLAMA_URL sem /api. Exemplo: http://127.0.0.1:11434" >&2
  exit 1
fi
if [[ "${http_code}" == "000" ]]; then
  echo "Nao consegui acessar ${preflight_url}" >&2
  echo "Verifique se o Ollama esta rodando e se a porta esta correta." >&2
  exit 1
fi

if [[ -z "${MODEL}" ]]; then
  MODEL="$(
    curl -fsS "${OLLAMA_URL}/api/tags" 2>/dev/null | jq -r '
      [
        .models[]
        | select((.name // "") | test("^(nomic-embed-text|.*embed.*)"; "i") | not)
        | .name
      ][0] // empty
    '
  )"
fi

if [[ -z "${MODEL}" ]]; then
  echo "Nao consegui detectar um modelo de chat disponivel em ${OLLAMA_URL}/api/tags" >&2
  echo "Defina OLLAMA_MODEL explicitamente, por exemplo: OLLAMA_MODEL=llama3.1:8b ow \"Teste\"" >&2
  exit 1
fi

start_ts=$(date +%s)
stop_monitor=0
first_chunk=0

cleanup() {
  stop_monitor=1
  if [[ -n "${monitor_pid:-}" ]]; then
    kill "${monitor_pid}" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

seconds_since_start() {
  local now
  now=$(date +%s)
  echo $((now - start_ts))
}

format_ns_to_ms() {
  awk -v ns="$1" 'BEGIN { printf "%.1f", ns / 1000000 }'
}

monitor_model() {
  while [[ "${stop_monitor}" -eq 0 ]]; do
    ps_json="$(curl -fsS "${OLLAMA_URL}/api/ps" 2>/dev/null || true)"
    if [[ -n "${ps_json}" ]]; then
      model_line="$(
        jq -r --arg model "${MODEL}" '
          .models[]
          | select(.name == $model or .model == $model)
          | "loaded name=\(.name) expires_at=\(.expires_at // \"unknown\") vram=\(.size_vram // 0)"
        ' <<<"${ps_json}" 2>/dev/null | head -n1
      )"
    else
      model_line=""
    fi

    if [[ -n "${model_line}" ]]; then
      printf '[%ss] /api/ps: %s\n' "$(seconds_since_start)" "${model_line}" >&2
    else
      printf '[%ss] /api/ps: model not listed as running\n' "$(seconds_since_start)" >&2
    fi

    sleep 2
  done
}

monitor_model &
monitor_pid=$!

request_body="$(
  jq -nc --arg model "${MODEL}" --arg prompt "${PROMPT}" '{
    model: $model,
    prompt: $prompt,
    stream: true
  }'
)"

echo "[0s] sending request to ${OLLAMA_URL}/api/generate using model ${MODEL}" >&2

curl -fsS -N \
  -H 'Content-Type: application/json' \
  -d "${request_body}" \
  "${OLLAMA_URL}/api/generate" |
while IFS= read -r line; do
  [[ -z "${line}" ]] && continue

  if ! jq -e . >/dev/null 2>&1 <<<"${line}"; then
    printf '\n[warn] non-JSON line: %s\n' "${line}" >&2
    continue
  fi

  error_message="$(jq -r '.error // empty' <<<"${line}")"
  if [[ -n "${error_message}" ]]; then
    printf '\n[error] %s\n' "${error_message}" >&2
    exit 1
  fi

  response_chunk="$(jq -r '.response // ""' <<<"${line}")"
  done_flag="$(jq -r '.done // false' <<<"${line}")"

  if [[ "${first_chunk}" -eq 0 && -n "${response_chunk}" ]]; then
    first_chunk=1
    printf '\n[%ss] first chunk received\n' "$(seconds_since_start)" >&2
  fi

  if [[ -n "${response_chunk}" ]]; then
    printf '%s' "${response_chunk}"
  fi

  if [[ "${done_flag}" == "true" ]]; then
    total_duration="$(jq -r '.total_duration // empty' <<<"${line}")"
    load_duration="$(jq -r '.load_duration // empty' <<<"${line}")"
    prompt_eval_duration="$(jq -r '.prompt_eval_duration // empty' <<<"${line}")"
    eval_duration="$(jq -r '.eval_duration // empty' <<<"${line}")"
    eval_count="$(jq -r '.eval_count // empty' <<<"${line}")"
    prompt_eval_count="$(jq -r '.prompt_eval_count // empty' <<<"${line}")"

    printf '\n\n[done] total=%sms load=%sms prompt=%sms eval=%sms prompt_tokens=%s output_tokens=%s\n' \
      "$(format_ns_to_ms "${total_duration:-0}")" \
      "$(format_ns_to_ms "${load_duration:-0}")" \
      "$(format_ns_to_ms "${prompt_eval_duration:-0}")" \
      "$(format_ns_to_ms "${eval_duration:-0}")" \
      "${prompt_eval_count:-0}" \
      "${eval_count:-0}" >&2
  fi
done
