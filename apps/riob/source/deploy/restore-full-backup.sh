#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

usage() {
  cat <<'EOF'
Uso:
  ./deploy/restore-full-backup.sh backupsSql/backup_full_YYYYMMDD_HHMMSS.tar.gz --yes

Restaura um backup completo gerado por /api/backup/full:
  - db/backup.sql no MariaDB do docker compose
  - app_data no volume app_data
  - cameras_data no volume cameras_data
  - relatorios no diretorio ./Relatorios

Aviso: esta operacao substitui dados existentes. Use em ambiente novo ou apos
gerar backup local do ambiente atual.
EOF
}

ARCHIVE=""
YES=0
for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
    -y|--yes)
      YES=1
      ;;
    *)
      if [ -z "$ARCHIVE" ]; then
        ARCHIVE="$arg"
      else
        echo "[restore-full] argumento inesperado: $arg" >&2
        usage >&2
        exit 2
      fi
      ;;
  esac
done

if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
  echo "[restore-full] informe um arquivo .tar.gz existente." >&2
  usage >&2
  exit 2
fi

if [ "$YES" != "1" ]; then
  printf "Restaurar %s e substituir dados atuais? [s/N] " "$ARCHIVE"
  read -r answer
  case "${answer,,}" in
    s|sim|y|yes) ;;
    *)
      echo "[restore-full] cancelado."
      exit 1
      ;;
  esac
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

echo "[restore-full] extraindo $ARCHIVE"
tar -xzf "$ARCHIVE" -C "$tmp_dir"

if [ ! -f "$tmp_dir/manifest.json" ] || [ ! -f "$tmp_dir/db/backup.sql" ]; then
  echo "[restore-full] arquivo nao parece ser um backup completo RioBranco valido." >&2
  exit 1
fi

if ! grep -q '"riobranco-full-backup-v1"' "$tmp_dir/manifest.json"; then
  echo "[restore-full] formato de manifest desconhecido." >&2
  exit 1
fi

env_value() {
  local key="$1"
  local default="$2"
  local value="${!key:-}"
  if [ -z "$value" ] && [ -f .env ]; then
    value="$(grep -E "^${key}=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- | sed -E "s/^['\"]//; s/['\"]$//" || true)"
  fi
  printf '%s' "${value:-$default}"
}

DB_NAME="$(env_value RB_DB_NAME riobranco)"
DB_USER="$(env_value RB_DB_USER riobranco)"
DB_PASSWORD="$(env_value RB_DB_PASSWORD riobranco123)"
DB_ROOT_PASSWORD="$(env_value RB_DB_ROOT_PASSWORD root123)"

echo "[restore-full] subindo MariaDB"
docker compose up -d db
docker compose stop app proxy >/dev/null 2>&1 || true
docker compose build app >/dev/null

echo "[restore-full] aguardando MariaDB aceitar conexao"
for _ in $(seq 1 60); do
  if docker compose exec -T db mariadb-admin ping -h 127.0.0.1 --protocol=tcp -uroot "-p${DB_ROOT_PASSWORD}" --silent >/dev/null 2>&1; then
    DB_MODE=root
    break
  fi
  if docker compose exec -T db mariadb-admin ping -h 127.0.0.1 --protocol=tcp -u"$DB_USER" "-p${DB_PASSWORD}" --silent >/dev/null 2>&1; then
    DB_MODE=app
    break
  fi
  sleep 2
done

DB_MODE="${DB_MODE:-}"
if [ -z "$DB_MODE" ]; then
  echo "[restore-full] MariaDB nao autenticou com root nem com usuario da aplicacao." >&2
  exit 1
fi

echo "[restore-full] restaurando banco ($DB_MODE)"
if [ "$DB_MODE" = "root" ]; then
  sed -E 's/CONSTRAINT `[^`]+` FOREIGN KEY/FOREIGN KEY/g' "$tmp_dir/db/backup.sql" \
    | docker compose exec -T db mariadb -uroot "-p${DB_ROOT_PASSWORD}"
else
  sed -E '
    s/CONSTRAINT `[^`]+` FOREIGN KEY/FOREIGN KEY/g
    /^\/\*!40000 DROP DATABASE IF EXISTS `[^`]+`\*\//d
    /^DROP DATABASE IF EXISTS /d
    /^CREATE DATABASE /d
    /^USE `[^`]+`;/d
  ' "$tmp_dir/db/backup.sql" \
    | docker compose exec -T db mariadb -u"$DB_USER" "-p${DB_PASSWORD}" "$DB_NAME"
fi

restore_compose_volume() {
  local source_dir="$1"
  local target_dir="$2"
  local label="$3"
  if [ ! -d "$source_dir" ]; then
    echo "[restore-full] $label nao encontrado no backup; pulando."
    return
  fi

  echo "[restore-full] restaurando $label em $target_dir"
  docker compose run --rm --no-deps -T \
    -v "$source_dir:/restore/source:ro" \
    app sh -lc "set -eu; mkdir -p '$target_dir'; find '$target_dir' -mindepth 1 -maxdepth 1 -exec rm -rf {} +; cp -a /restore/source/. '$target_dir'/"
}

restore_compose_volume "$tmp_dir/app_data" "/data/app" "app_data"
restore_compose_volume "$tmp_dir/cameras_data" "/data/cameras" "cameras_data"

if [ -d "$tmp_dir/relatorios" ]; then
  echo "[restore-full] restaurando Relatorios/"
  mkdir -p Relatorios
  find Relatorios -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  cp -a "$tmp_dir/relatorios/." Relatorios/
fi

echo "[restore-full] restore completo concluido."
echo "[restore-full] confira .env/certificados e suba app/proxy com: docker compose up -d --build app proxy"
