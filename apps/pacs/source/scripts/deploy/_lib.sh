#!/bin/sh
set -eu

if [ -z "${ROOT_DIR:-}" ]; then
  ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"
fi
if [ -n "${RAIOX_ENV_FILE:-}" ]; then
  ENV_FILE="$RAIOX_ENV_FILE"
elif [ -f "$ROOT_DIR/.env.docker" ]; then
  ENV_FILE="$ROOT_DIR/.env.docker"
elif [ -f "$ROOT_DIR/.env" ]; then
  # `.env` pode existir para execucao fora do Docker. Para a stack Compose,
  # preferimos `.env.docker` sempre que ele estiver disponivel.
  ENV_FILE="$ROOT_DIR/.env"
else
  ENV_FILE="$ROOT_DIR/.env.docker"
fi
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

write_default_env_docker_example() {
  cat > "$1" <<'EOF'
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=raioxpacs
POSTGRES_PORT=5433

PGHOST=db
PGPORT=5432
PGUSER=postgres
PGPASSWORD=postgres
PGDATABASE=raioxpacs
PGSSLMODE=prefer

APP_PORT=5020
APP_SECRET_KEY=troque-esta-chave-em-producao

WORKLIST_PORT=11115
WORKLIST_AE_TITLE=RAIOXMWL

PACS_AET=RAIOXPACS
PACS_STATION_AET=RAIOXPACS
PACS_INSTITUTION_NAME=Clinica de Radiologia
RAD_UID_ROOT=2.25

# Primeiro deploy deve deixar 1 para criar/atualizar schema e seeds.
# Para atualizacao sem mexer no banco, use scripts/deploy/update.sh.
AUTO_BOOTSTRAP_SCHEMA=1
EOF
}

compose() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1 && sudo docker compose version >/dev/null 2>&1; then
    sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
    return
  fi

  echo "Docker Compose nao esta disponivel. Rode scripts/deploy/first_boot.sh ou instale Docker manualmente." >&2
  exit 1
}

ensure_env_file() {
  if [ ! -f "$ROOT_DIR/.env.docker.example" ]; then
    if [ -f "$ROOT_DIR/.env.docker" ]; then
      cp "$ROOT_DIR/.env.docker" "$ROOT_DIR/.env.docker.example"
    elif [ -f "$ROOT_DIR/.env" ]; then
      cp "$ROOT_DIR/.env" "$ROOT_DIR/.env.docker.example"
    else
      write_default_env_docker_example "$ROOT_DIR/.env.docker.example"
    fi
  fi

  if [ ! -f "$ROOT_DIR/.env.docker" ]; then
    if [ -f "$ROOT_DIR/.env" ]; then
      cp "$ROOT_DIR/.env" "$ROOT_DIR/.env.docker"
    else
      cp "$ROOT_DIR/.env.docker.example" "$ROOT_DIR/.env.docker"
    fi
  fi

  # Mantemos um `.env` de compatibilidade para restores e comandos que ainda
  # esperam esse nome de arquivo no root do projeto.
  if [ ! -f "$ROOT_DIR/.env" ]; then
    cp "$ROOT_DIR/.env.docker" "$ROOT_DIR/.env"
  fi

  if [ ! -f "$ENV_FILE" ]; then
    cp "$ROOT_DIR/.env.docker" "$ENV_FILE"
  fi
}

ensure_runtime_dirs() {
  mkdir -p "$ROOT_DIR/runtime/imagebox"
  mkdir -p "$ROOT_DIR/runtime/cameras"
  mkdir -p "$ROOT_DIR/runtime/backups"
  mkdir -p "$ROOT_DIR/runtime/exam_attachments"
}
