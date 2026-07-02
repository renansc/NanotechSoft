#!/bin/sh
set -eu

. "$(CDPATH= cd -- "$(dirname "$0")" && pwd)/_lib.sh"

ensure_env_file
ensure_runtime_dirs

if [ "${RAIOX_SKIP_GIT_PULL:-0}" != "1" ] && [ -d "$ROOT_DIR/.git" ] && command -v git >/dev/null 2>&1; then
  git -C "$ROOT_DIR" pull --ff-only
fi

if [ "${RAIOX_SKIP_NETWORK_CHECK:-0}" != "1" ]; then
  "$ROOT_DIR/scripts/deploy/check-network.sh"
fi

export AUTO_BOOTSTRAP_SCHEMA=0

compose build app worklist dicom
compose up -d --no-deps app worklist dicom
compose ps app worklist dicom
