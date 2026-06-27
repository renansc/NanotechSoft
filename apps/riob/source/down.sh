#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "[riob-down] parando app, proxy e Open WebUI sem mexer no banco ou no Ollama..."
docker compose stop app proxy open-webui
docker compose ps app proxy open-webui
