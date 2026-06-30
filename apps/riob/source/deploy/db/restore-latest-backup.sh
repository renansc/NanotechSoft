#!/bin/sh
set -eu

log() {
  echo "[db-restore] $*"
}

DB_HOST="${MARIADB_HOST:-db}"
DB_PORT="${MARIADB_PORT:-3306}"
DB_NAME="${MARIADB_DATABASE:-riobranco}"
DB_ROOT_PASSWORD="${MARIADB_ROOT_PASSWORD:-}"
BACKUP_DIR="${RB_DB_BACKUP_DIR:-/backups}"
RESTORE_FORCE="${RB_DB_RESTORE_FORCE:-0}"

if [ -z "$DB_ROOT_PASSWORD" ]; then
  log "MARIADB_ROOT_PASSWORD nao definido; abortando restore."
  exit 1
fi

mysql_query() {
  mariadb \
    -h "$DB_HOST" \
    -P "$DB_PORT" \
    -uroot \
    "-p$DB_ROOT_PASSWORD" \
    "$DB_NAME" \
    -Nse "$1"
}

wait_for_db() {
  tries=0
  until mariadb-admin ping -h "$DB_HOST" -P "$DB_PORT" -uroot "-p$DB_ROOT_PASSWORD" --silent >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -ge 60 ]; then
      log "Banco nao ficou pronto a tempo."
      exit 1
    fi
    sleep 2
  done
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
  case "$backup_file" in
    *.sql.gz)
      gzip -cd "$backup_file" \
        | sed -E 's/CONSTRAINT `[^`]+` FOREIGN KEY/FOREIGN KEY/g' \
        | mariadb -h "$DB_HOST" -P "$DB_PORT" -uroot "-p$DB_ROOT_PASSWORD" "$DB_NAME"
      ;;
    *.sql)
      sed -E 's/CONSTRAINT `[^`]+` FOREIGN KEY/FOREIGN KEY/g' "$backup_file" \
        | mariadb -h "$DB_HOST" -P "$DB_PORT" -uroot "-p$DB_ROOT_PASSWORD" "$DB_NAME"
      ;;
    *)
      log "Formato de backup nao suportado: $backup_file"
      exit 1
      ;;
  esac
}

wait_for_db

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
