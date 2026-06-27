#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-git-safe"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

MESSAGE=""
NO_PUSH=0
SKIP_BUILD=0
SKIP_HEALTH=0
YES=0

usage() {
  cat <<'EOF'
Uso:
  ./deploy/git-safe-push.sh -m "mensagem do commit" [opcoes]

Opcoes:
  -m, --message TEXTO   Mensagem do commit
  -y, --yes             Nao pedir confirmacao interativa
  --no-push             Commitar, mas nao enviar para origin
  --skip-build          Pular docker compose build app
  --skip-health         Pular checagem local do app
  -h, --help            Mostrar ajuda

O script:
  - bloqueia arquivos sensiveis/runtime do stage
  - adiciona somente arquivos seguros
  - valida Python e docker compose
  - opcionalmente builda e testa o container app
  - commita e envia a branch atual para origin
EOF
}

is_risky_path() {
  local path="${1//\\//}"
  [[ "$path" == ".env" ]] && return 0
  [[ "$path" == .env.* && "$path" != ".env.example" ]] && return 0
  [[ "$path" == ".venv/"* ]] && return 0
  [[ "$path" == "__pycache__/"* ]] && return 0
  [[ "$path" == *.log ]] && return 0
  [[ "$path" == deploy/tmp/* ]] && return 0
  return 1
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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "opcao desconhecida: $1"
      ;;
  esac
done

ensure_command git
ensure_command docker
cd_project

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "nao estou dentro de um repositorio Git"

if [[ -z "$MESSAGE" ]]; then
  if [[ "$YES" == "1" ]]; then
    MESSAGE="Atualizacao operacional $(date '+%Y-%m-%d %H:%M')"
  else
    read -r -p "Mensagem do commit: " MESSAGE
  fi
fi
[[ -n "$MESSAGE" ]] || die "mensagem do commit vazia"

BRANCH="$(git branch --show-current)"
[[ -n "$BRANCH" && "$BRANCH" != "HEAD" ]] || die "nao foi possivel identificar a branch atual"

log "branch atual: $BRANCH"
git status --short --branch

log "limpando arquivos sensiveis/runtime do stage"
mapfile -t STAGED_FILES < <(git diff --cached --name-only)
for path in "${STAGED_FILES[@]}"; do
  if is_risky_path "$path"; then
    log "removendo do stage: $path"
    git restore --staged -- "$path"
  fi
done

log "adicionando arquivos seguros"
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

log "rodando validacoes"
git diff --check
python_cmd="python3"
if [[ -x ".venv/bin/python" ]]; then
  python_cmd=".venv/bin/python"
fi
"$python_cmd" -m py_compile app.py
compose config >/tmp/nanotechsoft-compose-config.yml

if [[ "$SKIP_BUILD" != "1" ]]; then
  log "validando build da imagem app"
  compose build "$APP_SERVICE"
fi

if [[ "$SKIP_HEALTH" != "1" ]]; then
  log "subindo app para checagem local"
  compose up -d "$DB_SERVICE" "$APP_SERVICE"
  if ! wait_for_app 45 2; then
    compose logs --tail=120 "$APP_SERVICE" >&2 || true
    die "falha ao consultar o app dentro do container"
  fi
fi

if ! confirm "Confirmar commit e envio para Git?"; then
  die "operacao cancelada"
fi

git commit -m "$MESSAGE"

if [[ "$NO_PUSH" == "1" ]]; then
  log "push pulado por --no-push"
  exit 0
fi

git remote get-url origin >/dev/null 2>&1 || die "remote origin nao configurado"
git push origin "$BRANCH"
log "enviado para origin/$BRANCH"
