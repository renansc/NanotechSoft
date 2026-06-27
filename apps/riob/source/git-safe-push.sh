#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

MESSAGE=""
NO_PUSH=0
SKIP_BUILD=0
SKIP_HEALTH=0
SKIP_BACKUP=0
YES=0

usage() {
  cat <<'EOF'
Uso:
  ./git-safe-push.sh -m "mensagem do commit" [opcoes]

Opcoes:
  -m, --message TEXTO   Mensagem do commit
  -y, --yes             Nao pedir confirmacao interativa
  --no-push             Commitar, mas nao enviar para origin
  --skip-build          Pular docker compose build app
  --skip-health         Pular checagem /api/status local
  --skip-backup         Pular backup SQL antes do push
  -h, --help            Mostrar ajuda

O script:
  - bloqueia arquivos sensiveis/runtime do stage
  - adiciona apenas arquivos seguros
  - roda validacoes antes de commitar
  - atualiza o container app e valida /api/status internamente
  - gera backup SQL antes de enviar ao Git, salvo --skip-backup
  - faz push da branch atual para origin
EOF
}

log() {
  printf '[git-safe-push] %s\n' "$*"
}

die() {
  printf '[git-safe-push] ERRO: %s\n' "$*" >&2
  exit 1
}

confirm() {
  if [[ "$YES" == "1" ]]; then
    return 0
  fi
  local answer
  read -r -p "$1 [s/N] " answer
  case "${answer,,}" in
    s|sim|y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

ensure_app_container() {
  log "garantindo container app para validacao local"
  if ! "${DOCKER_CMD[@]}" compose up -d --no-deps app; then
    "${DOCKER_CMD[@]}" compose logs --tail=120 app >&2 || true
    die "nao foi possivel subir o container app"
  fi
}

check_app_health() {
  local attempt
  for ((attempt=1; attempt<=45; attempt+=1)); do
    if "${DOCKER_CMD[@]}" compose exec -T app python - <<'PY' >/tmp/riob-git-safe-status.json 2>/tmp/riob-git-safe-status.err
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8080/api/status", timeout=5) as response:
    payload = json.loads(response.read().decode("utf-8", errors="replace"))

if not payload.get("api") or not payload.get("database"):
    raise SystemExit("api/status sem api/database OK")

print(json.dumps(payload))
PY
    then
      log "saude local OK"
      return 0
    fi
    sleep 2
  done

  if [[ -s /tmp/riob-git-safe-status.err ]]; then
    sed 's/^/[git-safe-push] app: /' /tmp/riob-git-safe-status.err >&2
  fi
  "${DOCKER_CMD[@]}" compose logs --tail=120 app >&2 || true
  die "falha ao consultar /api/status dentro do container app"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message)
      [[ $# -ge 2 ]] || die "faltou texto depois de $1"
      MESSAGE="$2"
      shift 2
      ;;
    -y|--yes)
      YES=1
      shift
      ;;
    --no-push)
      NO_PUSH=1
      shift
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    --skip-health)
      SKIP_HEALTH=1
      shift
      ;;
    --skip-backup)
      SKIP_BACKUP=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "opcao desconhecida: $1"
      ;;
  esac
done

command -v git >/dev/null 2>&1 || die "git nao encontrado"
command -v docker >/dev/null 2>&1 || die "docker nao encontrado"

DOCKER_CMD=(docker)
if ! docker info >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1; then
    DOCKER_CMD=(sudo docker)
    log "usando sudo docker porque o usuario atual ainda nao acessa /var/run/docker.sock"
  fi
fi

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "nao estou dentro de um repositorio Git"

if [[ -z "$MESSAGE" ]]; then
  if [[ "$YES" == "1" ]]; then
    MESSAGE="Atualizacao operacional $(date '+%Y-%m-%d %H:%M')"
  else
    read -r -p "Mensagem do commit: " MESSAGE
  fi
fi
[[ -n "$MESSAGE" ]] || die "mensagem do commit vazia"

HAS_HEAD=1
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  HAS_HEAD=0
fi

BRANCH="$(git branch --show-current)"
if [[ -z "$BRANCH" ]]; then
  BRANCH="$(git symbolic-ref --quiet --short HEAD || true)"
fi
[[ -n "$BRANCH" ]] || die "nao foi possivel identificar a branch atual"
[[ "$BRANCH" != "HEAD" ]] || die "checkout esta em detached HEAD"

log "branch atual: $BRANCH"
if [[ "$HAS_HEAD" == "0" ]]; then
  log "repositorio sem commits; preparando commit inicial"
fi
git status --short --branch

RISKY_PATTERNS=(
  '.env'
  '.env.*'
  'backupsSql/**'
  'sync-backups/**'
  'certs/**'
  'Relatorios/**'
  'DATA/**'
  'cameras/cams/**'
  'cameras/cams.json'
  'cameras/cameras.db'
  '**/*.ts'
  '**/live.m3u8'
)

is_risky_path() {
  local path="${1//\\//}"
  local base="${path##*/}"
  [[ "$path" == ".env.example" ]] && return 1
  [[ "$path" == ".env" ]] && return 0
  [[ "$path" == .env.* ]] && return 0
  [[ "$path" == backupsSql/* ]] && return 0
  [[ "$path" == sync-backups/* ]] && return 0
  [[ "$path" == certs/* ]] && return 0
  [[ "$path" == Relatorios/* ]] && return 0
  [[ "$path" == DATA/* ]] && return 0
  [[ "$path" == cameras/cams/* ]] && return 0
  [[ "$path" == cameras/cams.json ]] && return 0
  [[ "$path" == cameras/cameras.db ]] && return 0
  [[ "$path" == *.ts ]] && return 0
  [[ "$base" == live.m3u8 ]] && return 0
  return 1
}

log "limpando do stage arquivos sensiveis/runtime, se houver"
mapfile -t STAGED_FILES < <(git diff --cached --name-only)
for path in "${STAGED_FILES[@]}"; do
  if is_risky_path "$path"; then
    log "removendo do stage: $path"
    git restore --staged -- "$path"
  fi
done

log "adicionando somente arquivos seguros"
mapfile -d '' CHANGED_FILES < <(git ls-files --modified --deleted --others --exclude-standard -z)
SAFE_FILES=()
BLOCKED_FILES=()
for path in "${CHANGED_FILES[@]}"; do
  [[ -n "$path" ]] || continue
  if is_risky_path "$path"; then
    BLOCKED_FILES+=("$path")
  else
    SAFE_FILES+=("$path")
  fi
done

if [[ "${#BLOCKED_FILES[@]}" -gt 0 ]]; then
  log "arquivos bloqueados ignorados:"
  printf '  - %s\n' "${BLOCKED_FILES[@]}"
fi

if [[ "${#SAFE_FILES[@]}" -gt 0 ]]; then
  git add -- "${SAFE_FILES[@]}"
fi

mapfile -t FINAL_STAGED < <(git diff --cached --name-only)
if [[ "${#FINAL_STAGED[@]}" -eq 0 ]]; then
  log "nenhuma alteracao segura para commitar"
  exit 0
fi

for path in "${FINAL_STAGED[@]}"; do
  if is_risky_path "$path"; then
    die "arquivo sensivel/runtime ainda esta staged: $path"
  fi
done

log "resumo do commit"
git diff --cached --stat

log "rodando validacoes pre-commit"
git diff --check
python_cmd="python3"
if [[ -x ".venv/bin/python" ]]; then
  python_cmd=".venv/bin/python"
fi
"$python_cmd" -m py_compile server.py tools/riob_agent_web.py
"${DOCKER_CMD[@]}" compose config >/tmp/riob-compose-config.yml

if [[ "$SKIP_BUILD" != "1" ]]; then
  log "validando build da imagem app"
  "${DOCKER_CMD[@]}" compose build app
fi

if [[ "$SKIP_HEALTH" != "1" || "$SKIP_BACKUP" != "1" ]]; then
  ensure_app_container
fi

if [[ "$SKIP_HEALTH" != "1" ]]; then
  log "checando saude local em app:8080/api/status"
  check_app_health
fi

if [[ "$SKIP_BACKUP" != "1" ]]; then
  log "gerando backup SQL antes do push"
  "${DOCKER_CMD[@]}" compose exec -T app python - <<'PY'
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8080/api/backup", timeout=600) as resp:
    name = resp.headers.get("X-Backup-File") or "backup gerado"
    while resp.read(1024 * 1024):
        pass
print(f"[git-safe-push] backup: {name}")
PY
fi

if ! confirm "Confirmar commit e envio para Git?"; then
  die "operacao cancelada"
fi

git commit -m "$MESSAGE"

if [[ "$NO_PUSH" == "1" ]]; then
  log "push pulado por --no-push"
  exit 0
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  die "remote origin nao configurado; use: git remote add origin <URL_DO_REPOSITORIO>"
fi

git push origin "$BRANCH"
log "enviado para origin/$BRANCH"
log "para atualizar producao depois, use: ./update.sh $BRANCH"
