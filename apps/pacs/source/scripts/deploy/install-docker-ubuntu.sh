#!/bin/sh
set -eu

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "Docker e Docker Compose ja estao disponiveis."
  exit 0
fi

if [ ! -f /etc/os-release ]; then
  echo "Nao foi possivel identificar o sistema operacional." >&2
  exit 1
fi

. /etc/os-release

PLATFORM=" ${ID:-} ${ID_LIKE:-} "
case "$PLATFORM" in
  *" ubuntu "*|*" debian "*) ;;
  *)
    echo "Script automatico suportado para Ubuntu/Debian. Sistema atual: ${PRETTY_NAME:-desconhecido}." >&2
    exit 1
    ;;
esac

$SUDO apt-get update
$SUDO apt-get install -y ca-certificates curl gnupg
$SUDO install -m 0755 -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.asc ]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.asc
fi
$SUDO chmod a+r /etc/apt/keyrings/docker.asc

ARCH="$(dpkg --print-architecture)"
CODENAME="${VERSION_CODENAME:-$(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}")}"

echo \
  "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $CODENAME stable" \
  | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null

$SUDO apt-get update
$SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

if command -v systemctl >/dev/null 2>&1; then
  $SUDO systemctl enable docker >/dev/null 2>&1 || true
  $SUDO systemctl start docker >/dev/null 2>&1 || true
fi

if [ "$(id -u)" -ne 0 ] && command -v usermod >/dev/null 2>&1; then
  $SUDO usermod -aG docker "$USER" >/dev/null 2>&1 || true
fi

echo "Docker instalado com sucesso."
if [ "$(id -u)" -ne 0 ]; then
  echo "Se o comando docker ainda pedir permissao, abra uma nova sessao ou use sudo."
fi
