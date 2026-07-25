#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "[riob-down] parando app, proxy e Open WebUI sem mexer no Ollama..."
docker compose stop app proxy open-webui

echo "[riob-down] sincronizando banco da producao para a homologacao..."
RB_SYNC_CODE=0 \
RB_SYNC_DB=1 \
RB_SYNC_APP_DATA=0 \
RB_SYNC_CAMERAS_DATA=0 \
RB_SYNC_RESTART_SERVICES=0 \
  ./deploy/sync-production-to-homolog.sh

echo "[riob-down] garantindo app, proxy e Open WebUI parados apos a sincronizacao..."
docker compose stop app proxy open-webui
docker compose ps app proxy open-webui
