#!/bin/sh
set -eu

. "$(CDPATH= cd -- "$(dirname "$0")" && pwd)/_lib.sh"

SQL_FILE="${1:-$ROOT_DIR/scripts/update_tabela_exames_producao.sql}"
BACKUP_DIR="$ROOT_DIR/runtime/backups/exam-table"

ensure_env_file
ensure_runtime_dirs

set -a
. "$ENV_FILE"
set +a

DB_NAME="${PGDATABASE:-${POSTGRES_DB:-raioxpacs}}"
DB_USER="${PGUSER:-${POSTGRES_USER:-postgres}}"

if [ ! -f "$SQL_FILE" ]; then
  echo "Arquivo SQL nao encontrado: $SQL_FILE" >&2
  echo "Gere com: python scripts/generate_import_tabela_exames_sql.py --input scripts/examesatualizado.xlsx" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
backup_file="$BACKUP_DIR/catalogo-exames-antes-$(date +%Y%m%d-%H%M%S).sql"

echo "Gerando backup logico de raiox.procedure_catalog, raiox.convenio, raiox.convenio_price e settings de precos..."
compose exec -T -e DB_NAME="$DB_NAME" -e DB_USER="$DB_USER" db sh -c 'pg_dump \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  --data-only \
  --table=raiox.procedure_catalog \
  --table=raiox.convenio \
  --table=raiox.convenio_price \
  --table=raiox.system_settings' \
  > "$backup_file"

echo "Backup salvo em: $backup_file"
echo "Aplicando SQL em $DB_NAME: $SQL_FILE"
compose exec -T -e DB_NAME="$DB_NAME" -e DB_USER="$DB_USER" db sh -c 'psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME"' < "$SQL_FILE"

echo "Tabela de exames atualizada com sucesso."
