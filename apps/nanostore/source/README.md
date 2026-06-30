# NanoStore

Projeto novo de gestao para farmacia, separado do `zap`, usando-o apenas como referencia arquitetural.

## O que esta pronto

- cadastro de categorias, fornecedores e produtos
- controle por lote, validade e localizacao
- vendas por balcao, WhatsApp, WooCommerce, WordPress, Mercado Livre e delivery
- pagamentos com base para Pix e maquina de cartao
- configuracao de provedores e canais
- dashboard web inicial

## Rodar localmente

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Depois abra `http://127.0.0.1:5000`.

## Docker com MySQL

```bash
docker compose up --build
```

Depois abra:

- `http://127.0.0.1:8080`
- `https://127.0.0.1:8443`

Para celular na mesma rede, abra pelo IP da maquina:

- `https://SEU_IP_LOCAL:8443`

Exemplo:

- `https://192.168.0.10:8443`

Configuracao importante para HTTPS por IP:

- defina `CERT_APP_HOSTS` no `.env` com o IP usado pelo celular
- exemplo: `CERT_APP_HOSTS=192.168.0.10`
- se trocar o IP ou adicionar dominio, force a reemissao com `CERT_FORCE_REISSUE=1` e suba novamente

Fluxo recomendado para liberar a camera no celular:

1. acesse `http://SEU_IP_LOCAL:8080/mobile-setup`
2. toque em `Baixar CA Android`
3. instale/confie o certificado CA no aparelho
4. depois toque em `Abrir NanoStore em HTTPS`

Rotas leves para teste no celular:

- `GET /mobile-setup`
- `GET /healthz`

Endpoints de certificado disponiveis:

- `GET /api/ca/cert.pem`
- `GET /api/ca/cert.crt`
- `GET /api/app/cert.pem`
- `GET /api/app/cert.crt`

Banco padrao do compose:

- host: `db`
- porta: `3306`
- database: `nanostore`
- user: `renan`
- password: defina em `MYSQL_PASSWORD`

Se o MySQL ja tiver sido iniciado antes com outro usuario ou senha, remova o volume antigo e suba novamente:

```bash
docker compose down -v
docker compose up --build
```

Se ainda aparecer `container nanostore-mysql is unhealthy`, veja o log do banco:

```bash
docker compose logs db
```

Para MySQL `8.4`, o parametro antigo `default-authentication-plugin=mysql_native_password` nao funciona mais. O projeto foi ajustado para usar `--mysql-native-password=ON`, que e o formato compativel com MySQL 8.4.

O container da aplicacao tambem inclui `cryptography`, necessario quando o MySQL usa autenticacao `caching_sha2_password`.

## VSCodium

O workspace inclui `.vscode/settings.json` para abrir o terminal integrado como `bash -l`, ajudando o `VSCodium` a herdar o `PATH` correto e encontrar comandos como `docker`.

Observacoes desta entrega:

- o container da aplicacao aguarda o MySQL ficar saudavel antes de subir
- os `selects` principais de operacao usam dados vindos do banco
- na tela de vendas o produto aparece em `select` e a tela mostra a lista de produtos com `quantidade` e `valor`
- o compose agora usa `nginx` + bootstrap de certificados, no mesmo estilo do projeto `RioBranco`
- a CA interna e o certificado HTTPS ficam no diretorio `./certs`
- para webcam no celular, o navegador precisa confiar na CA interna instalada no aparelho
- quando a webcam nao estiver disponivel, o sistema esconde os botoes de scanner e mostra aviso com fallback manual
