#!/bin/sh
set -eu

. "$(CDPATH= cd -- "$(dirname "$0")" && pwd)/_lib.sh"

ensure_env_file
compose ps
