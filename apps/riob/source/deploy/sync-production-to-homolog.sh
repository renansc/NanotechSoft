#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[sync-prod-homolog] %s\n' "$*"
}

die() {
  printf '[sync-prod-homolog] ERRO: %s\n' "$*" >&2
  exit 1
}

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

[ -f .env ] || die ".env nao encontrado em $REPO_DIR"

set -a
. ./.env
set +a

PROD_BASE_URL="${RB_SYNC_PROD_BASE_URL:-https://192.168.200.254:8443}"
PROD_HOST="${RB_SYNC_PROD_HOST:-192.168.200.254}"
PROD_SSH_USER="${RB_SYNC_PROD_SSH_USER:-${USER:-root}}"
PROD_SSH_KEY="${RB_SYNC_PROD_SSH_KEY:-}"
SYNC_CODE="${RB_SYNC_CODE:-1}"
SYNC_DB="${RB_SYNC_DB:-1}"
SYNC_APP_DATA="${RB_SYNC_APP_DATA:-1}"
SYNC_CAMERAS_DATA="${RB_SYNC_CAMERAS_DATA:-0}"
CURL_INSECURE="${RB_SYNC_CURL_INSECURE:-1}"
SYNC_BRANCH="${RB_SYNC_BRANCH:-main}"
BACKUP_DIR="${RB_SYNC_BACKUP_DIR:-$REPO_DIR/sync-backups}"
RESET_NFE_CONFIG="${RB_SYNC_RESET_NFE_CONFIG:-1}"

[ "${RB_CERT_BOOTSTRAP:-0}" = "0" ] || die "Homologacao deve usar RB_CERT_BOOTSTRAP=0 antes da sincronizacao."
[ -n "${RB_DB_ROOT_PASSWORD:-}" ] || die "RB_DB_ROOT_PASSWORD nao definido no .env"

mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d_%H%M%S)"
local_db_backup="$BACKUP_DIR/homolog_db_before_sync_${timestamp}.sql.gz"
prod_db_dump="$BACKUP_DIR/producao_db_${timestamp}.sql"
local_app_backup="$BACKUP_DIR/homolog_app_data_before_sync_${timestamp}.tar.gz"
local_cameras_backup="$BACKUP_DIR/homolog_cameras_data_before_sync_${timestamp}.tar.gz"

curl_args=(--fail --show-error --location)
if [ "$CURL_INSECURE" = "1" ]; then
  curl_args+=(-k)
fi

ssh_args=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)
if [ -n "$PROD_SSH_KEY" ]; then
  ssh_args+=(-i "$PROD_SSH_KEY")
fi

ssh_remote="${PROD_SSH_USER}@${PROD_HOST}"

run_remote() {
  ssh "${ssh_args[@]}" "$ssh_remote" "$@"
}

resolve_volume_name() {
  local container_name="$1"
  local destination="$2"
  docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$destination\"}}{{.Name}}{{end}}{{end}}" "$container_name"
}

resolve_remote_volume_name() {
  local container_name="$1"
  local destination="$2"
  run_remote "docker inspect -f '{{range .Mounts}}{{if eq .Destination \"$destination\"}}{{.Name}}{{end}}{{end}}' $container_name"
}

backup_local_db() {
  log "Gerando backup do banco atual da homologacao em $local_db_backup"
  docker compose exec -T db mariadb-dump \
    -uroot \
    "-p$RB_DB_ROOT_PASSWORD" \
    --databases "${RB_DB_NAME:-riobranco}" \
    --routines --events --triggers \
    --single-transaction --quick \
    --add-drop-database --add-drop-table \
    --default-character-set=utf8mb4 \
    | gzip -c > "$local_db_backup"
}

fetch_prod_db_dump() {
  log "Baixando dump atual da producao de $PROD_BASE_URL/api/backup"
  curl "${curl_args[@]}" \
    "$PROD_BASE_URL/api/backup" \
    -o "$prod_db_dump"
}

import_prod_db_dump() {
  log "Importando dump da producao no banco da homologacao"
  sed -E 's/CONSTRAINT `[^`]+` FOREIGN KEY/FOREIGN KEY/g' "$prod_db_dump" \
    | docker compose exec -T db mariadb -uroot "-p$RB_DB_ROOT_PASSWORD"
}

reset_homolog_nfe_config() {
  [ "$RESET_NFE_CONFIG" = "1" ] || return 0
  log "Aplicando defaults seguros de NF-e para a homologacao"
  docker compose exec -T db mariadb -uroot "-p$RB_DB_ROOT_PASSWORD" "${RB_DB_NAME:-riobranco}" <<'SQL'
UPDATE nfe_config
SET
  habilitado = 0,
  ambiente = 'homologacao',
  ultimo_nsu = '',
  auto_manifestar_ciencia = 0,
  updated_at = NOW()
WHERE id = 1;
SQL
}

backup_named_volume() {
  local volume_name="$1"
  local output_file="$2"
  log "Gerando backup local do volume $volume_name em $output_file"
  docker run --rm -v "${volume_name}:/from:ro" alpine:3.20 \
    sh -lc 'cd /from && tar -czf - .' > "$output_file"
}

sync_remote_volume_to_local() {
  local remote_container="$1"
  local mount_path="$2"
  local local_container="$3"
  local local_mount="$4"
  local before_backup="$5"

  local remote_volume=""
  local local_volume=""

  remote_volume="$(resolve_remote_volume_name "$remote_container" "$mount_path")"
  [ -n "$remote_volume" ] || die "Nao foi possivel localizar o volume remoto $mount_path em $remote_container"

  local_volume="$(resolve_volume_name "$local_container" "$local_mount")"
  [ -n "$local_volume" ] || die "Nao foi possivel localizar o volume local $local_mount em $local_container"

  backup_named_volume "$local_volume" "$before_backup"

  log "Sincronizando volume remoto $remote_volume para o volume local $local_volume"
  run_remote "docker run --rm -v ${remote_volume}:/from:ro alpine:3.20 sh -lc 'cd /from && tar -cf - .'" \
    | docker run --rm -i -v "${local_volume}:/to" alpine:3.20 \
        sh -lc 'find /to -mindepth 1 -maxdepth 1 -exec rm -rf {} + && tar -xf - -C /to'
}

if [ "$SYNC_CODE" = "1" ]; then
  log "Atualizando codigo local pela branch $SYNC_BRANCH"
  git fetch origin
  git pull --ff-only origin "$SYNC_BRANCH"
fi

log "Parando app e proxy da homologacao para sincronizacao consistente"
docker compose stop app proxy >/dev/null

if [ "$SYNC_DB" = "1" ]; then
  backup_local_db
  fetch_prod_db_dump
  import_prod_db_dump
  reset_homolog_nfe_config
fi

if [ "$SYNC_APP_DATA" = "1" ]; then
  sync_remote_volume_to_local "riobranco-app" "/data/app" "riobranco-app" "/data/app" "$local_app_backup"
fi

if [ "$SYNC_CAMERAS_DATA" = "1" ]; then
  sync_remote_volume_to_local "riobranco-app" "/data/cameras" "riobranco-app" "/data/cameras" "$local_cameras_backup"
fi

log "Subindo servicos da homologacao"
docker compose up -d --build app proxy

log "Status final"
docker compose ps

log "Sincronizacao concluida."
log "Backups locais salvos em: $BACKUP_DIR"
