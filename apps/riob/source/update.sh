#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

RIOB_DEPLOY_LOG_PREFIX="riob-update"

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"

echo "[riob-update] atualizando codigo da branch ${BRANCH}..."
git pull --ff-only origin "$BRANCH"

# shellcheck source=deploy/lib/ollama.sh
source "$REPO_DIR/deploy/lib/ollama.sh"
# shellcheck source=deploy/lib/network.sh
source "$REPO_DIR/deploy/lib/network.sh"

configure_public_access_env
ensure_public_certificate

ensure_ollama_model
ensure_open_webui

echo "[riob-update] aplicando deploy sem restaurar ou substituir o banco..."
if [[ "${NO_CACHE:-0}" == "1" ]]; then
  docker compose build --no-cache app proxy
  docker compose up -d --no-deps app proxy
else
  docker compose up -d --build --no-deps app proxy
fi

./deploy/db/migrate-xml-fretes.sh

docker compose ps ollama open-webui app proxy
validate_public_access
