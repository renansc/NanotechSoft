#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="nanotechsoft-git-safe"
# shellcheck source=deploy/lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

MESSAGE=""
NO_PUSH=0
SKIP_BUILD=0
SKIP_HEALTH=0
SKIP_COMPOSE=0
SKIP_WHITESPACE=0
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
  --skip-compose        Pular validacao/build/health com Docker Compose
                        Se Docker Compose nao existir, o script faz este pulo automaticamente
  --skip-whitespace     Pular git diff --check
  -h, --help            Mostrar ajuda

O script:
  - bloqueia arquivos sensiveis/runtime do stage
  - adiciona somente arquivos seguros
  - valida Python, manifests dos apps, clientes e docker compose
  - opcionalmente builda e testa o container app
  - commita quando houver alteracoes seguras
  - envia a branch atual para origin quando houver commits pendentes
EOF
}

is_risky_path() {
  local path="${1//\\//}"
  [[ "$path" == ".env" ]] && return 0
  [[ "$path" == .env.* && "$path" != ".env.example" ]] && return 0
  [[ "$path" == .env_* ]] && return 0
  [[ "$path" == ".venv/"* ]] && return 0
  [[ "$path" == "__pycache__/"* ]] && return 0
  [[ "$path" == *.log ]] && return 0
  [[ "$path" == deploy/tmp/* ]] && return 0
  [[ "$path" == "apps/riob/source/config" ]] && return 0
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

pending_commit_count() {
  if git rev-parse --verify --quiet "origin/$BRANCH" >/dev/null; then
    git rev-list --count "origin/$BRANCH..HEAD"
  else
    git rev-list --count HEAD
  fi
}

run_whitespace_check() {
  if [[ "$SKIP_WHITESPACE" == "1" ]]; then
    log "checagem de whitespace pulada por --skip-whitespace"
    return 0
  fi

  local pathspecs=(
    .
    ":(exclude)**/*.min.js"
    ":(exclude)**/*.pdf"
    ":(exclude)**/*.png"
    ":(exclude)**/*.jpg"
    ":(exclude)**/*.jpeg"
    ":(exclude)**/*.gif"
    ":(exclude)**/*.webp"
    ":(exclude)apps/**/static/vendor/**"
    ":(exclude)apps/**/docs/vendor/**"
  )

  git diff --check -- "${pathspecs[@]}"
  git diff --cached --check -- "${pathspecs[@]}"
}

run_validations() {
  log "rodando validacoes"
  run_whitespace_check
  PYTHON_CMD="$(python_cmd)" || die "python nao encontrado"
  "$PYTHON_CMD" -m py_compile app.py
  validate_app_sources
  validate_client_contracts
  validate_portal_integrations
  if [[ "$SKIP_COMPOSE" != "1" ]]; then
    compose config >/tmp/nanotechsoft-compose-config.yml
  else
    log "validacao Docker Compose pulada por --skip-compose"
  fi

  if [[ "$SKIP_BUILD" != "1" ]]; then
    log "validando build da imagem app"
    compose build "$APP_SERVICE"
  fi

  if [[ "$SKIP_HEALTH" != "1" ]]; then
    log "subindo app para checagem local"
    compose up -d "$DB_SERVICE" "$PACS_DB_SERVICE" "$APP_SERVICE"
    if ! wait_for_app 45 2; then
      compose logs --tail=120 "$APP_SERVICE" >&2 || true
      die "falha ao consultar o app dentro do container"
    fi
  fi
}

push_branch() {
  if [[ "$NO_PUSH" == "1" ]]; then
    log "push pulado por --no-push"
    exit 0
  fi

  git remote get-url origin >/dev/null 2>&1 || die "remote origin nao configurado"
  git push origin "$BRANCH"
  log "enviado para origin/$BRANCH"
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
    --skip-compose)
      SKIP_COMPOSE=1
      SKIP_BUILD=1
      SKIP_HEALTH=1
      shift
      ;;
    --skip-whitespace)
      SKIP_WHITESPACE=1
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
cd_project
if [[ "$SKIP_COMPOSE" != "1" ]]; then
  if ! detect_compose; then
    log "Docker Compose nao encontrado; pulando compose/build/health automaticamente"
    SKIP_COMPOSE=1
    SKIP_BUILD=1
    SKIP_HEALTH=1
  fi
fi

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "nao estou dentro de um repositorio Git"

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
  PENDING_COMMITS="$(pending_commit_count)"
  if [[ "$PENDING_COMMITS" -gt 0 ]]; then
    log "nenhuma alteracao segura para commitar; $PENDING_COMMITS commit(s) pendente(s) para enviar"
    run_validations
    if ! confirm "Confirmar envio dos commits pendentes para Git?"; then
      die "operacao cancelada"
    fi
    push_branch
  fi
  log "nenhuma alteracao segura para commitar e nenhum commit pendente para enviar"
  exit 0
fi

for path in "${FINAL_STAGED[@]}"; do
  if is_risky_path "$path"; then
    die "arquivo sensivel/runtime ainda esta staged: $path"
  fi
done

log "resumo do commit"
git diff --cached --stat

run_validations

if [[ -z "$MESSAGE" ]]; then
  if [[ "$YES" == "1" ]]; then
    MESSAGE="Atualizacao operacional $(date '+%Y-%m-%d %H:%M')"
  else
    read -r -p "Mensagem do commit: " MESSAGE
  fi
fi
[[ -n "$MESSAGE" ]] || die "mensagem do commit vazia"

if ! confirm "Confirmar commit e envio para Git?"; then
  die "operacao cancelada"
fi

git commit -m "$MESSAGE"

push_branch
