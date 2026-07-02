#!/bin/sh
set -eu

. "$(CDPATH= cd -- "$(dirname "$0")" && pwd)/_lib.sh"

ensure_env_file
ensure_runtime_dirs

if [ "${RAIOX_SKIP_NETWORK_CHECK:-0}" != "1" ]; then
  "$ROOT_DIR/scripts/deploy/check-network.sh"
fi

compose pull db || true
compose up -d --build --remove-orphans
compose ps
