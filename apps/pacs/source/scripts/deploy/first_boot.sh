#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"

# O bootstrap local deve privilegiar subir a stack sem depender de um teste
# externo de conectividade. Se precisar do diagnostico, rode check-network.sh
# manualmente ou sobrescreva esta variavel antes de chamar o script.
export RAIOX_SKIP_NETWORK_CHECK="${RAIOX_SKIP_NETWORK_CHECK:-1}"

if ! command -v docker >/dev/null 2>&1; then
  "$ROOT_DIR/scripts/deploy/install-docker-ubuntu.sh"
elif ! docker compose version >/dev/null 2>&1; then
  if ! command -v sudo >/dev/null 2>&1 || ! sudo docker compose version >/dev/null 2>&1; then
    "$ROOT_DIR/scripts/deploy/install-docker-ubuntu.sh"
  fi
fi

"$ROOT_DIR/scripts/deploy/up.sh"
