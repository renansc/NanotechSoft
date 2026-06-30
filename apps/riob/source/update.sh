#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="${1:-main}"

cd "$REPO_DIR"

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo ".env criado a partir de .env.example. Revise as senhas antes de usar em producao."
fi

echo "[1/4] Buscando atualizacoes do GitHub..."
git fetch origin

echo "[2/4] Aplicando branch ${BRANCH}..."
git pull --ff-only origin "$BRANCH"

echo "[3/4] Recriando containers com a versao nova..."
docker compose up -d --build

echo "[4/4] Limpeza opcional de imagens antigas..."
docker image prune -f >/dev/null 2>&1 || true

echo "Atualizacao concluida."
