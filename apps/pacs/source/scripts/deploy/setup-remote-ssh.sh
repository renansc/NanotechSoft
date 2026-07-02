#!/bin/sh
set -eu

MAINT_USER="${RAIOX_MAINT_USER:-raioxadmin}"
SSH_PORT="${RAIOX_SSH_PORT:-22}"
PUBLIC_KEY="${RAIOX_SSH_PUBLIC_KEY:-}"
PUBLIC_KEY_FILE="${RAIOX_SSH_PUBLIC_KEY_FILE:-}"
ALLOW_CIDR="${RAIOX_SSH_ALLOW_CIDR:-}"
KEEP_PASSWORD_LOGIN=0
PASSWORDLESS_SUDO=0

usage() {
  cat <<'EOF'
Uso:
  setup-remote-ssh.sh --public-key "ssh-ed25519 AAAA..."
  setup-remote-ssh.sh --public-key-file ./minha-chave.pub

Opcoes:
  --user <nome>              Usuario de manutencao. Padrao: raioxadmin
  --port <porta>             Porta SSH. Padrao: 22
  --allow-cidr <cidr>        Origem liberada no UFW, ex: 200.10.20.30/32
  --keep-password-login      Nao desativa login por senha no SSH
  --passwordless-sudo        Permite sudo sem senha para o usuario criado

Variaveis equivalentes:
  RAIOX_MAINT_USER
  RAIOX_SSH_PORT
  RAIOX_SSH_PUBLIC_KEY
  RAIOX_SSH_PUBLIC_KEY_FILE
  RAIOX_SSH_ALLOW_CIDR

Depois, acesse de fora com:
  ssh -p <porta> <usuario>@<ip-ou-dns-da-producao>
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --user)
      MAINT_USER="${2:-}"
      shift 2
      ;;
    --port)
      SSH_PORT="${2:-}"
      shift 2
      ;;
    --public-key)
      PUBLIC_KEY="${2:-}"
      shift 2
      ;;
    --public-key-file)
      PUBLIC_KEY_FILE="${2:-}"
      shift 2
      ;;
    --allow-cidr)
      ALLOW_CIDR="${2:-}"
      shift 2
      ;;
    --keep-password-login)
      KEEP_PASSWORD_LOGIN=1
      shift
      ;;
    --passwordless-sudo)
      PASSWORDLESS_SUDO=1
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

case "$MAINT_USER" in
  ""|root)
    echo "Informe um usuario de manutencao valido, diferente de root." >&2
    exit 1
    ;;
  *[!a-zA-Z0-9_-]*)
    echo "Usuario invalido: $MAINT_USER" >&2
    exit 1
    ;;
esac

case "$SSH_PORT" in
  ""|*[!0-9]*)
    echo "Porta SSH invalida: $SSH_PORT" >&2
    exit 1
    ;;
esac

if [ "$SSH_PORT" -lt 1 ] || [ "$SSH_PORT" -gt 65535 ]; then
  echo "Porta SSH fora da faixa: $SSH_PORT" >&2
  exit 1
fi

if [ -n "$PUBLIC_KEY_FILE" ]; then
  if [ ! -f "$PUBLIC_KEY_FILE" ]; then
    echo "Arquivo de chave publica nao encontrado: $PUBLIC_KEY_FILE" >&2
    exit 1
  fi
  PUBLIC_KEY="$(sed -n '1p' "$PUBLIC_KEY_FILE")"
fi

if [ -z "$PUBLIC_KEY" ]; then
  echo "Informe a chave publica com --public-key ou --public-key-file." >&2
  exit 1
fi

case "$PUBLIC_KEY" in
  ssh-ed25519\ *|ssh-rsa\ *|ecdsa-sha2-nistp256\ *|ecdsa-sha2-nistp384\ *|ecdsa-sha2-nistp521\ *) ;;
  *)
    echo "Chave publica SSH invalida. Use o conteudo do arquivo .pub, nao a chave privada." >&2
    exit 1
    ;;
esac

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
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
$SUDO apt-get install -y openssh-server ufw

if ! id "$MAINT_USER" >/dev/null 2>&1; then
  $SUDO adduser --disabled-password --gecos "" "$MAINT_USER"
fi

$SUDO usermod -aG sudo "$MAINT_USER"
if getent group docker >/dev/null 2>&1; then
  $SUDO usermod -aG docker "$MAINT_USER"
fi

home_dir="$(getent passwd "$MAINT_USER" | cut -d: -f6)"
ssh_dir="$home_dir/.ssh"
auth_keys="$ssh_dir/authorized_keys"

$SUDO install -d -m 700 -o "$MAINT_USER" -g "$MAINT_USER" "$ssh_dir"
$SUDO touch "$auth_keys"
$SUDO chown "$MAINT_USER:$MAINT_USER" "$auth_keys"
$SUDO chmod 600 "$auth_keys"

if ! $SUDO grep -Fxq "$PUBLIC_KEY" "$auth_keys"; then
  printf '%s\n' "$PUBLIC_KEY" | $SUDO tee -a "$auth_keys" >/dev/null
fi

config_dir="/etc/ssh/sshd_config.d"
config_file="$config_dir/99-raiox-maintenance.conf"
$SUDO install -d -m 755 "$config_dir"

if [ "$KEEP_PASSWORD_LOGIN" -eq 1 ]; then
  password_auth="yes"
  keyboard_auth="yes"
else
  password_auth="no"
  keyboard_auth="no"
fi

tmp_config="$(mktemp)"
cat > "$tmp_config" <<EOF
# Gerenciado por scripts/deploy/setup-remote-ssh.sh
Port $SSH_PORT
PubkeyAuthentication yes
PasswordAuthentication $password_auth
KbdInteractiveAuthentication $keyboard_auth
PermitRootLogin no
X11Forwarding no
AllowTcpForwarding yes
ClientAliveInterval 300
ClientAliveCountMax 2
EOF

$SUDO cp "$tmp_config" "$config_file"
rm -f "$tmp_config"

if ! grep -Eq '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config; then
  $SUDO cp /etc/ssh/sshd_config "/etc/ssh/sshd_config.bak.$(date +%Y%m%d%H%M%S)"
  printf '\nInclude /etc/ssh/sshd_config.d/*.conf\n' | $SUDO tee -a /etc/ssh/sshd_config >/dev/null
fi

if [ "$PASSWORDLESS_SUDO" -eq 1 ]; then
  printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$MAINT_USER" | $SUDO tee "/etc/sudoers.d/90-$MAINT_USER" >/dev/null
  $SUDO chmod 440 "/etc/sudoers.d/90-$MAINT_USER"
  $SUDO visudo -cf "/etc/sudoers.d/90-$MAINT_USER" >/dev/null
fi

if command -v ufw >/dev/null 2>&1; then
  ufw_state="$($SUDO ufw status | sed -n '1s/.*:[[:space:]]*//p' | tr '[:upper:]' '[:lower:]' || true)"
  case "$ufw_state" in
    active|ativo)
      if [ -n "$ALLOW_CIDR" ]; then
        $SUDO ufw allow from "$ALLOW_CIDR" to any port "$SSH_PORT" proto tcp
      else
        $SUDO ufw allow "$SSH_PORT/tcp"
      fi
      ;;
    *)
      echo "UFW esta inativo; nenhuma regra de firewall foi ativada automaticamente."
      echo "Se houver firewall externo/roteador, libere TCP $SSH_PORT para este servidor."
      ;;
  esac
else
  echo "UFW nao encontrado; ajuste o firewall externo para liberar TCP $SSH_PORT."
fi

SSHD_BIN="$(command -v sshd || true)"
if [ -z "$SSHD_BIN" ] && [ -x /usr/sbin/sshd ]; then
  SSHD_BIN="/usr/sbin/sshd"
fi
if [ -z "$SSHD_BIN" ]; then
  echo "sshd nao encontrado apos instalar openssh-server." >&2
  exit 1
fi

$SUDO "$SSHD_BIN" -t

if command -v systemctl >/dev/null 2>&1; then
  $SUDO systemctl enable ssh >/dev/null 2>&1 || $SUDO systemctl enable sshd >/dev/null 2>&1 || true
  $SUDO systemctl restart ssh >/dev/null 2>&1 || $SUDO systemctl restart sshd >/dev/null 2>&1 || true
else
  $SUDO service ssh restart >/dev/null 2>&1 || $SUDO service sshd restart >/dev/null 2>&1 || true
fi

cat <<EOF
Acesso SSH de manutencao configurado.

Usuario: $MAINT_USER
Porta: $SSH_PORT
Login por senha: $(if [ "$KEEP_PASSWORD_LOGIN" -eq 1 ]; then echo "mantido"; else echo "desativado"; fi)

Teste em outro terminal antes de fechar esta sessao:
  ssh -p $SSH_PORT $MAINT_USER@IP_OU_DNS_DA_PRODUCAO

Se o servidor estiver atras de roteador/NAT, encaminhe a porta TCP $SSH_PORT para o IP interno deste servidor.
EOF
