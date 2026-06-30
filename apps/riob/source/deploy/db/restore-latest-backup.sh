#!/bin/sh
set -eu

log() {
  echo "[db-restore] $*"
}

DB_HOST="${MARIADB_HOST:-db}"
DB_PORT="${MARIADB_PORT:-3306}"
DB_NAME="${MARIADB_DATABASE:-riobranco}"
DB_APP_USER="${MARIADB_USER:-riobranco}"
DB_APP_PASSWORD="${MARIADB_PASSWORD:-riobranco123}"
DB_ROOT_PASSWORD="${MARIADB_ROOT_PASSWORD:-}"
BACKUP_DIR="${RB_DB_BACKUP_DIR:-/backups}"
RESTORE_FORCE="${RB_DB_RESTORE_FORCE:-0}"
DB_CLI_USER=""
DB_CLI_PASSWORD=""
DB_CLI_MODE=""

db_exec() {
  mariadb \
    -h "$DB_HOST" \
    -P "$DB_PORT" \
    -u"$DB_CLI_USER" \
    "-p$DB_CLI_PASSWORD" \
    "$@"
}

mysql_query() {
  db_exec "$DB_NAME" -Nse "$1"
}

wait_for_db() {
  tries=0
  until mariadb-admin ping -h "$DB_HOST" -P "$DB_PORT" --silent >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -ge 60 ]; then
      log "Banco nao ficou pronto a tempo."
      exit 1
    fi
    sleep 2
  done
}

select_db_credentials() {
  tries=0
  while [ "$tries" -lt 60 ]; do
    if [ -n "$DB_ROOT_PASSWORD" ] \
      && mariadb -h "$DB_HOST" -P "$DB_PORT" -uroot "-p$DB_ROOT_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; then
      DB_CLI_USER="root"
      DB_CLI_PASSWORD="$DB_ROOT_PASSWORD"
      DB_CLI_MODE="root"
      log "Credencial MariaDB root validada para restore."
      return 0
    fi

    if mariadb -h "$DB_HOST" -P "$DB_PORT" -u"$DB_APP_USER" "-p$DB_APP_PASSWORD" "$DB_NAME" -e "SELECT 1" >/dev/null 2>&1; then
      DB_CLI_USER="$DB_APP_USER"
      DB_CLI_PASSWORD="$DB_APP_PASSWORD"
      DB_CLI_MODE="app"
      log "MARIADB_ROOT_PASSWORD nao autenticou; usando usuario do banco da aplicacao para restore."
      return 0
    fi

    tries=$((tries + 1))
    sleep 2
  done

  log "Nao foi possivel autenticar no MariaDB com root nem com MARIADB_USER."
  exit 1
}

latest_backup() {
  preferred_backup="$(find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'backup_*.sql' -o -name 'backup_*.sql.gz' \) -printf '%f\n' | sort -r | head -n 1)"
  if [ -n "$preferred_backup" ]; then
    printf '%s/%s\n' "$BACKUP_DIR" "$preferred_backup"
    return
  fi

  find "$BACKUP_DIR" -maxdepth 1 -type f \( -name '*.sql' -o -name '*.sql.gz' \) -printf '%f\n' \
    | sort -r \
    | head -n 1 \
    | sed "s#^#$BACKUP_DIR/#"
}

db_is_empty() {
  tables_present="$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${DB_NAME}' AND table_name IN ('usuarios','veiculos','motoristas','cargas','conferentes','fretes','devolucoes','abastecimentos');")"
  if [ "${tables_present:-0}" -lt 8 ]; then
    return 0
  fi

  business_rows="$(mysql_query "SELECT
    COALESCE((SELECT COUNT(*) FROM veiculos), 0) +
    COALESCE((SELECT COUNT(*) FROM motoristas), 0) +
    COALESCE((SELECT COUNT(*) FROM cargas), 0) +
    COALESCE((SELECT COUNT(*) FROM conferentes), 0) +
    COALESCE((SELECT COUNT(*) FROM fretes), 0) +
    COALESCE((SELECT COUNT(*) FROM devolucoes), 0) +
    COALESCE((SELECT COUNT(*) FROM abastecimentos), 0);")"
  users_count="$(mysql_query "SELECT COALESCE((SELECT COUNT(*) FROM usuarios), 0);")"

  if [ "${business_rows:-0}" -gt 0 ]; then
    return 1
  fi

  if [ "${users_count:-0}" -gt 1 ]; then
    return 1
  fi

  return 0
}

restore_backup() {
  backup_file="$1"
  log "Restaurando backup: $backup_file"
  sed_script='
    s/CONSTRAINT `[^`]+` FOREIGN KEY/FOREIGN KEY/g
  '
  if [ "$DB_CLI_MODE" = "app" ]; then
    log "Restaurando com usuario restrito no banco $DB_NAME; comandos globais de database serao ignorados."
    sed_script='
      s/CONSTRAINT `[^`]+` FOREIGN KEY/FOREIGN KEY/g
      /^\/\*!40000 DROP DATABASE IF EXISTS `[^`]+`\*\//d
      /^DROP DATABASE IF EXISTS /d
      /^CREATE DATABASE /d
      /^USE `[^`]+`;/d
    '
  fi

  case "$backup_file" in
    *.sql.gz)
      gzip -cd "$backup_file" \
        | sed -E "$sed_script" \
        | db_exec "$DB_NAME"
      ;;
    *.sql)
      sed -E "$sed_script" "$backup_file" \
        | db_exec "$DB_NAME"
      ;;
    *)
      log "Formato de backup nao suportado: $backup_file"
      exit 1
      ;;
  esac
}

wait_for_db
select_db_credentials

if [ ! -d "$BACKUP_DIR" ]; then
  log "Diretorio de backup nao encontrado: $BACKUP_DIR. Nenhuma restauracao executada."
  exit 0
fi

backup_file="$(latest_backup)"
if [ -z "$backup_file" ]; then
  log "Nenhum arquivo .sql ou .sql.gz encontrado em $BACKUP_DIR. Nenhuma restauracao executada."
  exit 0
fi

if [ "$RESTORE_FORCE" != "1" ] && ! db_is_empty; then
  log "Banco ja contem dados; pulando restauracao."
  exit 0
fi

restore_backup "$backup_file"
log "Restauracao concluida."
