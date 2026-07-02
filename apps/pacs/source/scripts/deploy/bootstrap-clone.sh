#!/bin/sh
set -eu

usage() {
  cat <<'EOF'
Uso:
  bootstrap-clone.sh --repo <url> [--dir <pasta>] [--branch <branch>]
    [--git-name <nome>] [--git-email <email>]
    [--cred-protocol <http|https>] [--cred-host <host>] [--cred-user <usuario>] [--cred-token <token>]
    [--skip-deploy]

Variaveis de ambiente equivalentes:
  GIT_REPO_URL
  GIT_TARGET_DIR
  GIT_BRANCH
  GIT_USER_NAME
  GIT_USER_EMAIL
  GIT_CREDENTIAL_HOST
  GIT_CREDENTIAL_USERNAME
  GIT_CREDENTIAL_TOKEN

Exemplo:
  GIT_REPO_URL=https://github.com/seu-org/raioxPacs.git \
  GIT_TARGET_DIR=/srv/raioxPacs \
  GIT_USER_NAME="Seu Nome" \
  GIT_USER_EMAIL="voce@exemplo.com" \
  GIT_CREDENTIAL_USERNAME="seu-usuario" \
  GIT_CREDENTIAL_TOKEN="seu-token" \
  ./scripts/deploy/bootstrap-clone.sh
EOF
}

repo_url="${GIT_REPO_URL:-}"
target_dir="${GIT_TARGET_DIR:-}"
branch="${GIT_BRANCH:-main}"
git_name="${GIT_USER_NAME:-}"
git_email="${GIT_USER_EMAIL:-}"
cred_host="${GIT_CREDENTIAL_HOST:-}"
cred_protocol="${GIT_CREDENTIAL_PROTOCOL:-https}"
cred_user="${GIT_CREDENTIAL_USERNAME:-}"
cred_token="${GIT_CREDENTIAL_TOKEN:-}"
skip_deploy=0

if ! command -v git >/dev/null 2>&1; then
  echo "Git nao foi encontrado no PATH." >&2
  exit 1
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      repo_url="${2:-}"
      shift 2
      ;;
    --dir)
      target_dir="${2:-}"
      shift 2
      ;;
    --branch)
      branch="${2:-}"
      shift 2
      ;;
    --git-name)
      git_name="${2:-}"
      shift 2
      ;;
    --git-email)
      git_email="${2:-}"
      shift 2
      ;;
    --cred-host)
      cred_host="${2:-}"
      shift 2
      ;;
    --cred-protocol)
      cred_protocol="${2:-}"
      shift 2
      ;;
    --cred-user)
      cred_user="${2:-}"
      shift 2
      ;;
    --cred-token)
      cred_token="${2:-}"
      shift 2
      ;;
    --skip-deploy)
      skip_deploy=1
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

if [ -z "$repo_url" ]; then
  echo "Falta informar a URL do repositorio com --repo ou GIT_REPO_URL." >&2
  usage >&2
  exit 1
fi

if [ -z "$target_dir" ]; then
  repo_name="${repo_url##*/}"
  repo_name="${repo_name%.git}"
  target_dir="$PWD/$repo_name"
fi

if [ -d "$target_dir" ] && [ -n "$(ls -A "$target_dir" 2>/dev/null)" ]; then
  echo "O diretorio alvo ja existe e nao esta vazio: $target_dir" >&2
  exit 1
fi

mkdir -p "$(dirname "$target_dir")"

if [ "$branch" = "" ]; then
  git clone "$repo_url" "$target_dir"
else
  git clone --branch "$branch" --single-branch "$repo_url" "$target_dir"
fi

if [ -n "$git_name" ]; then
  git -C "$target_dir" config user.name "$git_name"
fi

if [ -n "$git_email" ]; then
  git -C "$target_dir" config user.email "$git_email"
fi

if [ -n "$cred_user" ] || [ -n "$cred_token" ] || [ -n "$cred_host" ]; then
  if [ -z "$cred_user" ] || [ -z "$cred_token" ]; then
    echo "Para configurar credenciais, informe tanto --cred-user quanto --cred-token." >&2
    exit 1
  fi

  if [ -z "$cred_host" ]; then
    case "$repo_url" in
      http://*)
        cred_protocol="http"
        cred_host="${repo_url#*://}"
        cred_host="${cred_host%%/*}"
        cred_host="${cred_host#*@}"
        ;;
      https://*)
        cred_protocol="https"
        cred_host="${repo_url#*://}"
        cred_host="${cred_host%%/*}"
        cred_host="${cred_host#*@}"
        ;;
      *)
        echo "Nao foi possivel inferir o host do repositorio. Use --cred-host." >&2
        exit 1
        ;;
    esac
  fi

  git -C "$target_dir" config credential.helper store
  printf 'protocol=%s\nhost=%s\nusername=%s\npassword=%s\n\n' \
    "$cred_protocol" "$cred_host" "$cred_user" "$cred_token" | git -C "$target_dir" credential approve
fi

if [ "$skip_deploy" -eq 1 ]; then
  echo "Clone concluido em $target_dir."
  exit 0
fi

echo "Clone concluido. Iniciando o primeiro deploy local..."
(cd "$target_dir" && sh scripts/deploy/first_boot.sh)

echo "Ambiente pronto."
echo "Acesso web: http://localhost:5020"
echo "PACS DICOM: localhost:11112"
echo "Worklist DICOM: localhost:11115"
