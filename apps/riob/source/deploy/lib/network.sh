#!/usr/bin/env bash

riob_env_file_value() {
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

configure_public_access_env() {
  local prefix
  prefix="${RIOB_DEPLOY_LOG_PREFIX:-riob}"

  echo "[${prefix}] proxy e Open WebUI configurados para acesso de rede em 0.0.0.0."
}

ensure_public_certificate() {
  local prefix enabled
  prefix="${RIOB_DEPLOY_LOG_PREFIX:-riob}"
  enabled="${RB_ENABLE_HTTPS:-$(riob_env_file_value RB_ENABLE_HTTPS)}"
  if [[ "$enabled" != "1" ]]; then
    return 0
  fi

  echo "[${prefix}] validando certificado HTTPS para o IP/DNS configurado..."
  docker compose build cert-bootstrap
  docker compose run --rm cert-bootstrap
}

riob_public_base_url() {
  local enabled host port configured
  configured="${RB_PUBLIC_BASE_URL:-$(riob_env_file_value RB_PUBLIC_BASE_URL)}"
  if [[ -n "$configured" ]]; then
    printf '%s\n' "${configured%/}"
    return 0
  fi

  enabled="${RB_ENABLE_HTTPS:-$(riob_env_file_value RB_ENABLE_HTTPS)}"
  host="${RB_SERVER_NAME:-$(riob_env_file_value RB_SERVER_NAME)}"
  if [[ -z "$host" || "$host" == "_" ]]; then
    return 1
  fi

  if [[ "$enabled" == "1" ]]; then
    port="${RB_HTTPS_PORT:-$(riob_env_file_value RB_HTTPS_PORT)}"
    port="${port:-443}"
    if [[ "$port" == "443" ]]; then
      printf 'https://%s\n' "$host"
    else
      printf 'https://%s:%s\n' "$host" "$port"
    fi
  else
    port="${RB_HTTP_PORT:-$(riob_env_file_value RB_HTTP_PORT)}"
    port="${port:-80}"
    if [[ "$port" == "80" ]]; then
      printf 'http://%s\n' "$host"
    else
      printf 'http://%s:%s\n' "$host" "$port"
    fi
  fi
}

validate_public_access() {
  local prefix base webui_port attempt body proxy_binding webui_binding public_ok webui_ok
  prefix="${RIOB_DEPLOY_LOG_PREFIX:-riob}"
  public_ok=0
  base="$(riob_public_base_url)" || {
    echo "[${prefix}] ERRO: defina RB_SERVER_NAME ou RB_PUBLIC_BASE_URL com o IP/DNS da maquina." >&2
    return 1
  }

  proxy_binding="$(docker compose port proxy 80 2>/dev/null || true)"
  if [[ "$proxy_binding" != 0.0.0.0:* && "$proxy_binding" != \[::\]:* ]]; then
    echo "[${prefix}] ERRO: proxy nao esta publicado em todas as interfaces: ${proxy_binding:-sem porta}." >&2
    return 1
  fi

  echo "[${prefix}] validando acesso publicado em ${base}/api/status..."
  for ((attempt=1; attempt<=90; attempt+=1)); do
    if body="$(curl --silent --show-error --fail --insecure --connect-timeout 5 --max-time 15 "${base}/api/status" 2>/dev/null)" \
      && grep -Eq '"api"[[:space:]]*:[[:space:]]*true' <<<"$body" \
      && grep -Eq '"database"[[:space:]]*:[[:space:]]*true' <<<"$body"; then
      echo "[${prefix}] acesso pelo IP/DNS validado: ${base}"
      public_ok=1
      break
    fi
    sleep 2
  done
  if [[ "$public_ok" != "1" ]]; then
    echo "[${prefix}] ERRO: ${base}/api/status nao respondeu pelo endereco publicado." >&2
    echo "[${prefix}] confira o IP da VM e libere as portas HTTP/HTTPS no firewall do host." >&2
    return 1
  fi

  webui_port="${RB_OPEN_WEBUI_PORT:-$(riob_env_file_value RB_OPEN_WEBUI_PORT)}"
  webui_port="${webui_port:-3000}"
  webui_binding="$(docker compose port open-webui 8080 2>/dev/null || true)"
  if [[ "$webui_binding" != 0.0.0.0:* && "$webui_binding" != \[::\]:* ]]; then
    echo "[${prefix}] ERRO: Open WebUI nao esta publicado em todas as interfaces: ${webui_binding:-sem porta}." >&2
    return 1
  fi

  echo "[${prefix}] validando Open WebUI publicado na porta ${webui_port}..."
  webui_ok=0
  for ((attempt=1; attempt<=90; attempt+=1)); do
    if curl --silent --show-error --fail --connect-timeout 5 --max-time 15 \
      "http://127.0.0.1:${webui_port}/health" >/dev/null 2>&1; then
      webui_ok=$((webui_ok + 1))
      if [[ "$webui_ok" -ge 3 ]]; then
        echo "[${prefix}] Open WebUI validado na porta ${webui_port}."
        return 0
      fi
    else
      webui_ok=0
    fi
    sleep 2
  done

  echo "[${prefix}] ERRO: Open WebUI nao permaneceu saudavel na porta ${webui_port}." >&2
  docker compose logs --tail=120 open-webui >&2 || true
  return 1
}
