#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-status"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

cd_project
require_compose

compose ps
