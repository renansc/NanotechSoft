#!/bin/sh
set -eu

check_url() {
  url="$1"
  label="$2"
  http_code="$(curl -sSIL -o /dev/null -w '%{http_code}' --max-time 12 "$url" 2>/dev/null || true)"
  case "$http_code" in
    200|204|301|302|307|308|401)
      echo "Conectividade OK para $label (HTTP $http_code)."
      return 0
      ;;
  esac

  if [ -n "$http_code" ]; then
    echo "Falha ao acessar $label ($url), HTTP $http_code." >&2
  else
    echo "Falha ao acessar $label ($url), sem resposta HTTP." >&2
  fi
  return 1
}

if check_url "https://registry-1.docker.io/v2/" "Docker Hub" && check_url "https://pypi.org/" "PyPI"; then
  exit 0
fi

cat >&2 <<'EOF'
Sem conectividade HTTPS de saida a partir deste host/WSL.

O deploy do raioXPacs precisa baixar:
- imagem do PostgreSQL no Docker Hub
- imagem/base Python e dependencias

Pelo diagnostico, o problema e de rede/firewall/proxy do host, nao do projeto.

Proximos passos:
1. Teste no WSL:
   curl -I https://www.google.com
   curl -I https://registry-1.docker.io/v2/
2. Se estiver atras de proxy corporativo, configure HTTP_PROXY e HTTPS_PROXY no shell e no servico do Docker.
3. Se nao usa proxy, reinicie a rede do WSL/Windows:
   wsl --shutdown
   netsh winsock reset
4. Libere saida TCP 443 para o WSL/Docker no firewall/antivirus.

Se as imagens ja estiverem baixadas localmente, rode:
RAIOX_SKIP_NETWORK_CHECK=1 ./scripts/deploy/up.sh
EOF

exit 1
