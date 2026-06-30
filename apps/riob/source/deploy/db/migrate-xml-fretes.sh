#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

echo "[xml-fretes] aguardando o container app..."
for tentativa in $(seq 1 60); do
  if docker compose exec -T app python - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("http://127.0.0.1:8080/api/status", timeout=5).read()
PY
  then
    break
  fi
  if [[ "$tentativa" == "60" ]]; then
    echo "[xml-fretes] ERRO: app nao respondeu a tempo." >&2
    exit 1
  fi
  sleep 2
done

echo "[xml-fretes] reconciliando a logistica dos XMLs de saida..."
docker compose exec -T app \
  python /app/deploy/db/migrate_xml_fretes.py "$@"
