#!/bin/sh
set -eu

. "$(CDPATH= cd -- "$(dirname "$0")" && pwd)/_lib.sh"

ensure_env_file
if [ "$#" -gt 0 ]; then
  compose logs -f "$1"
else
  compose logs -f
fi
