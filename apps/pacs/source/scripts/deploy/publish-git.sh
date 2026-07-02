#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"
REMOTE="${GIT_REMOTE:-origin}"
BRANCH="${GIT_BRANCH:-}"
MESSAGE="${GIT_COMMIT_MESSAGE:-}"
DRY_RUN=0
SKIP_CHECKS=0
REMOTE_URL=""
SSH_KEY_FILE="${GIT_SSH_KEY_FILE:-}"
GIT_SSH_COMMAND_EFFECTIVE="${GIT_SSH_COMMAND:-}"

usage() {
  cat <<'EOF'
Uso:
  scripts/deploy/publish-git.sh -m "mensagem do commit" [--remote origin] [--branch main]
  scripts/deploy/publish-git.sh
  scripts/deploy/publish-git.sh --dry-run

O script:
  - respeita .gitignore;
  - bloqueia envio de .env, runtime, dumps, backups e arquivos grandes comuns;
  - valida scripts/Python quando possivel;
  - faz commit e push;
  - publica junto o fluxo seguro de producao: scripts/deploy/update.sh.

Na producao, atualize com:
  cd /srv/RaioxPacs
  ./scripts/deploy/update.sh
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -m|--message)
      MESSAGE="${2:-}"
      shift 2
      ;;
    --remote)
      REMOTE="${2:-origin}"
      shift 2
      ;;
    --branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --skip-checks)
      SKIP_CHECKS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Opcao desconhecida: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

cd "$ROOT_DIR"

if ! command -v git >/dev/null 2>&1; then
  echo "Git nao encontrado no PATH." >&2
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Este diretorio nao parece ser um repositorio Git: $ROOT_DIR" >&2
  exit 1
fi

REMOTE_URL="$(git remote get-url "$REMOTE" 2>/dev/null || true)"
if [ -z "$REMOTE_URL" ]; then
  echo "Remote Git nao encontrado: $REMOTE" >&2
  exit 1
fi

detect_ssh_key_file() {
  for key in \
    "$HOME/.ssh/id_ed25519" \
    "$HOME/.ssh/id_ed25519_github" \
    "$HOME/.ssh/id_rsa" \
    "$HOME/.ssh/id_rsa_github"
  do
    if [ -f "$key" ]; then
      printf '%s\n' "$key"
      return 0
    fi
  done
  return 1
}

setup_git_ssh() {
  case "$REMOTE_URL" in
    git@*:*|ssh://*)
      ;;
    *)
      return 0
      ;;
  esac

  if [ -n "$GIT_SSH_COMMAND_EFFECTIVE" ]; then
    export GIT_SSH_COMMAND="$GIT_SSH_COMMAND_EFFECTIVE"
    return 0
  fi

  if [ -z "$SSH_KEY_FILE" ]; then
    SSH_KEY_FILE="$(detect_ssh_key_file || true)"
  fi

  if [ -z "$SSH_KEY_FILE" ]; then
    echo "Remote SSH detectado, mas nenhuma chave privada foi encontrada." >&2
    echo "Defina GIT_SSH_KEY_FILE ou crie ~/.ssh/id_ed25519, ~/.ssh/id_ed25519_github, ~/.ssh/id_rsa ou ~/.ssh/id_rsa_github." >&2
    exit 1
  fi

  if [ ! -f "$SSH_KEY_FILE" ]; then
    echo "Arquivo de chave SSH nao encontrado: $SSH_KEY_FILE" >&2
    exit 1
  fi

  export GIT_SSH_COMMAND="ssh -i \"$SSH_KEY_FILE\" -o IdentitiesOnly=yes"
}

setup_git_ssh

if [ -z "$BRANCH" ]; then
  BRANCH="$(git branch --show-current)"
fi

if [ -z "$BRANCH" ]; then
  echo "Nao foi possivel descobrir a branch atual. Informe --branch." >&2
  exit 1
fi

if [ "$DRY_RUN" -eq 0 ] && [ -z "$MESSAGE" ]; then
  MESSAGE="atualiza codigo $(date '+%Y-%m-%d %H:%M')"
  echo "Mensagem de commit nao informada; usando: $MESSAGE"
fi

is_blocked_path() {
  case "$1" in
    .env|.env.*|render.env)
      case "$1" in
        *.example) return 1 ;;
        *) return 0 ;;
      esac
      ;;
    runtime/*|pgdata/*|__pycache__/*|.venv/*)
      return 0
      ;;
    *Zone.Identifier|*.pyc|*.log|*.bak|*.backup|*.dump|*.sql.gz|*.tar|*.tar.gz|*.zip)
      return 0
      ;;
  esac
  return 1
}

status_file="$(mktemp)"
trap 'rm -f "$status_file"' EXIT
git status --porcelain > "$status_file"

if [ ! -s "$status_file" ]; then
  echo "Nenhuma alteracao para publicar."
  exit 0
fi

blocked=""
while IFS= read -r line; do
  state="$(printf '%s' "$line" | cut -c 1-2)"
  path="${line#???}"
  case "$path" in
    *" -> "*)
      path="${path##* -> }"
      ;;
  esac
  [ -n "$path" ] || continue

  if is_blocked_path "$path" && [ "$state" != "D " ] && [ "$state" != " D" ]; then
    blocked="${blocked}
${path}"
  fi
done < "$status_file"

if [ -n "$blocked" ]; then
  echo "Publicacao bloqueada. Estes arquivos nao devem ir para o Git:" >&2
  printf '%s\n' "$blocked" >&2
  echo "Remova-os do stage/repo ou ajuste .gitignore antes de publicar." >&2
  exit 1
fi

if [ "$SKIP_CHECKS" -eq 0 ]; then
  if command -v sh >/dev/null 2>&1; then
    sh -n scripts/deploy/update.sh
    sh -n scripts/deploy/up.sh
    sh -n scripts/deploy/first_boot.sh
    sh -n scripts/deploy/_lib.sh
    sh -n docker/entrypoint.sh
  fi

  if command -v python >/dev/null 2>&1; then
    python -m compileall raiox_pacs scripts
  elif command -v python3 >/dev/null 2>&1; then
    python3 -m compileall raiox_pacs scripts
  fi
fi

echo "Alteracoes que serao publicadas:"
git status --short

if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry-run concluido. Nada foi commitado ou enviado."
  exit 0
fi

if [ -n "${GIT_SSH_COMMAND:-}" ]; then
  echo "Usando chave SSH para Git: ${SSH_KEY_FILE:-configurada via GIT_SSH_COMMAND}"
fi

if git ls-remote --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
  git fetch "$REMOTE" "$BRANCH"
  remote_ref="refs/remotes/$REMOTE/$BRANCH"
  if git rev-parse --verify "$remote_ref" >/dev/null 2>&1; then
    if ! git merge-base --is-ancestor "$remote_ref" HEAD; then
      echo "A branch remota $REMOTE/$BRANCH tem commits que nao estao aqui." >&2
      echo "Atualize primeiro com: git pull --ff-only $REMOTE $BRANCH" >&2
      exit 1
    fi
  fi
fi

git add -A

staged_file="$(mktemp)"
trap 'rm -f "$status_file" "$staged_file"' EXIT
git diff --cached --name-status > "$staged_file"
staged_blocked=""
while IFS="$(printf '\t')" read -r state path rest; do
  [ -n "$path" ] || continue
  case "$state" in
    R*)
      path="$rest"
      ;;
  esac
  if is_blocked_path "$path" && [ "$state" != "D" ]; then
    staged_blocked="${staged_blocked}
${path}"
  fi
done < "$staged_file"

if [ -n "$staged_blocked" ]; then
  echo "Publicacao bloqueada apos stage. Arquivos proibidos:" >&2
  printf '%s\n' "$staged_blocked" >&2
  exit 1
fi

if git diff --cached --quiet; then
  echo "Nenhuma alteracao valida ficou staged para commit."
  exit 0
fi

git commit -m "$MESSAGE"
git push -u "$REMOTE" "HEAD:$BRANCH"

cat <<EOF
Codigo enviado para $REMOTE/$BRANCH.

Para atualizar a producao sem derrubar o banco Docker:
  cd /srv/RaioxPacs
  ./scripts/deploy/update.sh

Esse update reconstrui app/worklist/dicom com AUTO_BOOTSTRAP_SCHEMA=0 e --no-deps.
EOF
