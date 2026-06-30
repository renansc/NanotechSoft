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

load_env_file() {
  while IFS= read -r raw_line || [ -n "$raw_line" ]; do
    line="${raw_line#"${raw_line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [ -n "$line" ] || continue
    case "$line" in
      \#*) continue ;;
    esac
    case "$line" in
      *=*)
        key="${line%%=*}"
        value="${line#*=}"
        key="${key%"${key##*[![:space:]]}"}"
        value="${value#"${value%%[![:space:]]*}"}"
        if [ "${value#\"}" != "$value" ] && [ "${value%\"}" != "$value" ]; then
          value="${value#\"}"
          value="${value%\"}"
        elif [ "${value#\'}" != "$value" ] && [ "${value%\'}" != "$value" ]; then
          value="${value#\'}"
          value="${value%\'}"
        fi
        export "$key=$value"
        ;;
    esac
  done < ./.env
}

load_env_file

PROD_BASE_URL="${RB_SYNC_PROD_BASE_URL:-https://192.168.200.254}"
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
VALIDATE_DB_SYNC="${RB_SYNC_VALIDATE_DB:-1}"
DB_NAME="${RB_DB_NAME:-riobranco}"
DB_APP_USER="${RB_DB_USER:-riobranco}"
DB_APP_PASSWORD="${RB_DB_PASSWORD:-riobranco123}"
DB_CLI_USER=""
DB_CLI_PASSWORD=""
DB_CLI_MODE=""
services_stopped=0

[ "${RB_CERT_BOOTSTRAP:-0}" = "0" ] || die "Homologacao deve usar RB_CERT_BOOTSTRAP=0 antes da sincronizacao."

mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d_%H%M%S)"
local_db_backup="$BACKUP_DIR/homolog_db_before_sync_${timestamp}.sql.gz"
prod_db_dump="$BACKUP_DIR/producao_db_${timestamp}.sql"
prod_db_snapshot="$BACKUP_DIR/producao_db_${timestamp}.snapshot.json"
homolog_db_snapshot="$BACKUP_DIR/homolog_db_${timestamp}.snapshot.json"
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

db_exec() {
  docker compose exec -T db mariadb -u"$DB_CLI_USER" "-p$DB_CLI_PASSWORD" "$@"
}

db_dump() {
  docker compose exec -T db mariadb-dump -u"$DB_CLI_USER" "-p$DB_CLI_PASSWORD" "$@"
}

select_db_credentials() {
  if [ -n "${RB_DB_ROOT_PASSWORD:-}" ] \
    && docker compose exec -T db mariadb -uroot "-p$RB_DB_ROOT_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; then
    DB_CLI_USER="root"
    DB_CLI_PASSWORD="$RB_DB_ROOT_PASSWORD"
    DB_CLI_MODE="root"
    log "Credencial MariaDB root validada para backup/importacao."
    return 0
  fi

  if docker compose exec -T db mariadb -u"$DB_APP_USER" "-p$DB_APP_PASSWORD" "$DB_NAME" -e "SELECT 1" >/dev/null 2>&1; then
    DB_CLI_USER="$DB_APP_USER"
    DB_CLI_PASSWORD="$DB_APP_PASSWORD"
    DB_CLI_MODE="app"
    log "RB_DB_ROOT_PASSWORD nao autenticou; usando usuario do banco da aplicacao para backup/importacao."
    return 0
  fi

  die "Nao foi possivel autenticar no MariaDB com root nem com RB_DB_USER. Confira RB_DB_ROOT_PASSWORD/RB_DB_PASSWORD no .env ou a senha gravada no volume do banco."
}

cleanup_on_error() {
  local status=$?
  if [ "$status" -ne 0 ] && [ "$services_stopped" = "1" ]; then
    log "Erro detectado; subindo app e proxy novamente."
    docker compose up -d app proxy >/dev/null || true
  fi
  exit "$status"
}

trap cleanup_on_error EXIT

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
  db_dump \
    --databases "$DB_NAME" \
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

validate_prod_db_dump() {
  [ "$VALIDATE_DB_SYNC" = "1" ] || return 0
  log "Validando dump da producao antes da importacao"

  [ -s "$prod_db_dump" ] || die "Dump da producao vazio: $prod_db_dump"

  if head -c 64 "$prod_db_dump" | grep -qiE '^\s*(<html|<!doctype|[{[])'; then
    die "O arquivo baixado de /api/backup nao parece SQL. Confira autenticao, URL e resposta da producao: $prod_db_dump"
  fi

  grep -qE '^(-- MariaDB dump|-- MySQL dump)' "$prod_db_dump" \
    || die "Dump sem cabecalho MariaDB/MySQL esperado: $prod_db_dump"
  grep -q 'CREATE TABLE `' "$prod_db_dump" \
    || die "Dump nao contem CREATE TABLE; importacao abortada para evitar homologacao incompleta."

  python3 - "$prod_db_dump" "$prod_db_snapshot" <<'PY'
import json
import re
import sys

dump_path, snapshot_path = sys.argv[1:3]
tables = {}
current_table = None
inside_insert = None

create_re = re.compile(r"^CREATE TABLE `([^`]+)`")
column_re = re.compile(r"^\s+`([^`]+)`\s+(.+?)(?:,)?$")
insert_re = re.compile(r"^INSERT INTO `([^`]+)` VALUES(?:\s*(.*))?$")

def count_rows_fragment(fragment: str) -> int:
    fragment = fragment.strip()
    if not fragment:
        return 0
    fragment = fragment.rstrip(";")
    return fragment.count("),(") + (1 if fragment.startswith("(") else 0)

with open(dump_path, "r", encoding="utf-8", errors="replace") as dump:
    for raw in dump:
        line = raw.rstrip("\n")
        match = create_re.match(line)
        if match:
            current_table = match.group(1)
            tables.setdefault(current_table, {"columns": [], "rows": 0})
            continue

        if current_table:
            if line.startswith(") ENGINE"):
                current_table = None
                continue
            column = column_re.match(line)
            if column:
                tables[current_table]["columns"].append(column.group(1))
            continue

        match = insert_re.match(line)
        if match:
            inside_insert = match.group(1)
            tables.setdefault(inside_insert, {"columns": [], "rows": 0})
            tables[inside_insert]["rows"] += count_rows_fragment(match.group(2) or "")
            if line.rstrip().endswith(";"):
                inside_insert = None
            continue

        if inside_insert:
            if line.lstrip().startswith("("):
                tables[inside_insert]["rows"] += count_rows_fragment(line)
            if line.rstrip().endswith(";"):
                inside_insert = None

if not tables:
    raise SystemExit("nenhuma tabela encontrada no dump")

with open(snapshot_path, "w", encoding="utf-8") as out:
    json.dump(tables, out, ensure_ascii=False, indent=2, sort_keys=True)
PY

  log "Dump validado: $(python3 - "$prod_db_snapshot" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
print(f"{len(data)} tabelas, {sum(item.get('rows', 0) for item in data.values())} linhas")
PY
)"
}

import_prod_db_dump() {
  log "Importando dump da producao no banco da homologacao"
  if [ "$DB_CLI_MODE" = "root" ]; then
    sed -E 's/CONSTRAINT `[^`]+` FOREIGN KEY/FOREIGN KEY/g' "$prod_db_dump" \
      | db_exec
    return 0
  fi

  log "Importando com usuario restrito no banco $DB_NAME; comandos globais de database serao ignorados."
  sed -E '
    s/CONSTRAINT `[^`]+` FOREIGN KEY/FOREIGN KEY/g
    /^\/\*!40000 DROP DATABASE IF EXISTS `[^`]+`\*\//d
    /^DROP DATABASE IF EXISTS /d
    /^CREATE DATABASE /d
    /^USE `[^`]+`;/d
  ' "$prod_db_dump" | db_exec "$DB_NAME"
}

snapshot_homolog_db() {
  [ "$VALIDATE_DB_SYNC" = "1" ] || return 0
  log "Coletando snapshot do banco importado na homologacao"
  python3 - "$prod_db_snapshot" "$homolog_db_snapshot" "$DB_NAME" "$DB_CLI_USER" "$DB_CLI_PASSWORD" <<'PY'
import json
import subprocess
import sys
import tempfile
from pathlib import Path

prod_snapshot, homolog_snapshot, db_name, db_user, db_password = sys.argv[1:6]
with open(prod_snapshot, encoding="utf-8") as f:
    prod = json.load(f)

tables = sorted(prod)
quoted_tables = ",".join("'" + table.replace("'", "''") + "'" for table in tables)
columns_sql = f"""
SELECT TABLE_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY ORDINAL_POSITION SEPARATOR ',')
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ({quoted_tables})
GROUP BY TABLE_NAME
ORDER BY TABLE_NAME;
"""

count_sql_parts = [
    f"SELECT '{table.replace(chr(39), chr(39) + chr(39))}' AS table_name, COUNT(*) AS row_count FROM `{table.replace('`', '``')}`"
    for table in tables
]
counts_sql = "\nUNION ALL\n".join(count_sql_parts) + ";\n"

def run_sql(sql: str) -> str:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
        tmp.write(sql)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as stdin:
            proc = subprocess.run(
                [
                    "docker", "compose", "exec", "-T", "db",
                    "mariadb",
                    f"-u{db_user}",
                    f"-p{db_password}",
                    db_name,
                    "-B", "-N",
                ],
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if proc.returncode != 0:
        raise SystemExit((proc.stderr or proc.stdout or "falha ao consultar banco").strip())
    return proc.stdout

columns = {}
for line in run_sql(columns_sql).splitlines():
    table, cols = line.split("\t", 1)
    columns[table] = cols.split(",") if cols else []

counts = {}
for line in run_sql(counts_sql).splitlines():
    table, count = line.split("\t", 1)
    counts[table] = int(count)

snapshot = {
    table: {
        "columns": columns.get(table, []),
        "rows": counts.get(table),
    }
    for table in tables
}
with open(homolog_snapshot, "w", encoding="utf-8") as out:
    json.dump(snapshot, out, ensure_ascii=False, indent=2, sort_keys=True)
PY
}

validate_imported_db() {
  [ "$VALIDATE_DB_SYNC" = "1" ] || return 0
  snapshot_homolog_db
  log "Conferindo se homologacao recebeu todas as tabelas, campos e linhas do dump"

  python3 - "$prod_db_snapshot" "$homolog_db_snapshot" <<'PY'
import json
import sys

prod_path, homolog_path = sys.argv[1:3]
with open(prod_path, encoding="utf-8") as f:
    prod = json.load(f)
with open(homolog_path, encoding="utf-8") as f:
    homolog = json.load(f)

errors = []
for table, expected in sorted(prod.items()):
    actual = homolog.get(table)
    if actual is None:
        errors.append(f"tabela ausente: {table}")
        continue

    expected_columns = expected.get("columns", [])
    actual_columns = actual.get("columns", [])
    missing_columns = [column for column in expected_columns if column not in actual_columns]
    if missing_columns:
        errors.append(f"{table}: campos ausentes: {', '.join(missing_columns)}")

    expected_rows = int(expected.get("rows") or 0)
    actual_rows = actual.get("rows")
    if actual_rows is None:
        errors.append(f"{table}: nao foi possivel contar linhas")
    elif int(actual_rows) != expected_rows:
        errors.append(f"{table}: linhas divergentes producao={expected_rows} homologacao={actual_rows}")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)

print(f"OK: {len(prod)} tabelas validadas.")
PY
}

reset_homolog_nfe_config() {
  [ "$RESET_NFE_CONFIG" = "1" ] || return 0
  log "Aplicando defaults seguros de NF-e para a homologacao"
  db_exec "$DB_NAME" <<'SQL'
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

select_db_credentials

log "Parando app e proxy da homologacao para sincronizacao consistente"
docker compose stop app proxy >/dev/null
services_stopped=1

if [ "$SYNC_DB" = "1" ]; then
  backup_local_db
  fetch_prod_db_dump
  validate_prod_db_dump
  import_prod_db_dump
  validate_imported_db
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
services_stopped=0

log "Status final"
docker compose ps

log "Sincronizacao concluida."
log "Backups locais salvos em: $BACKUP_DIR"
