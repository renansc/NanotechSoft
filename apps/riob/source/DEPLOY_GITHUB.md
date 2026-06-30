# Deploy via GitHub

## Preparacao

1. Copie `.env.example` para `.env`.
2. Ajuste as senhas do banco, `FLASK_SECRET`, `UI_*`, `ESXI_*` e `RB_FREEPBX_*`.
3. Ajuste `RB_SERVER_NAME` e `RB_PUBLIC_BASE_URL` com o IP ou DNS real usado pelos clientes.
4. Se `80` ou `443` ja estiverem ocupadas no host, ajuste `RB_HTTP_PORT` e `RB_HTTPS_PORT`.
5. Se quiser restore automatico em banco vazio, deixe o backup `.sql` ou `.sql.gz` em `backups sql/`.
6. O monitor ESXi fica versionado em `esxi/`; altere `RB_VSPHERE_CLIENT_PATH` apenas se quiser outra copia local.

## Certificados e WSS

O deploy padrao agora faz isso automaticamente:

- gera uma CA interna
- gera o certificado HTTPS da aplicacao
- gera o certificado WSS do FreePBX
- instala o certificado WSS no FreePBX

Regra importante quando varias VMs apontam para o mesmo FreePBX:

- deixe `RB_CERT_BOOTSTRAP=1` apenas na VM oficial
- use `RB_CERT_BOOTSTRAP=0` nas VMs secundarias ou de homologacao

Isso evita que uma VM sobrescreva o certificado WSS da outra.

## Exemplos de .env

Producao oficial:

```env
RB_ENABLE_HTTPS=1
RB_SERVER_NAME=192.168.200.254
RB_PUBLIC_BASE_URL=https://192.168.200.254:8443
RB_HTTP_PORT=8080
RB_HTTPS_PORT=8443
RB_CERT_BOOTSTRAP=1
RB_CERT_APP_HOSTS=192.168.200.254
RB_CERT_PBX_HOSTS=192.168.200.253,freepbx.sangoma.local,localhost,127.0.0.1
RB_FREEPBX_HOST=192.168.200.253
RB_FREEPBX_SSH_PORT=22
RB_FREEPBX_SSH_USER=root
RB_FREEPBX_SSH_PASS=troque-esta-senha-freepbx
```

VM secundaria ou homologacao usando o mesmo FreePBX:

```env
RB_ENABLE_HTTPS=1
RB_SERVER_NAME=192.168.200.250
RB_PUBLIC_BASE_URL=https://192.168.200.250:8443
RB_HTTP_PORT=8080
RB_HTTPS_PORT=8443
RB_CERT_BOOTSTRAP=0
RB_FREEPBX_HOST=192.168.200.253
RB_FREEPBX_SSH_PORT=22
RB_FREEPBX_SSH_USER=root
RB_FREEPBX_SSH_PASS=troque-esta-senha-freepbx
```

## Primeira subida

```bash
docker compose up -d --build
```

Comportamento padrao:

- `cert-bootstrap` prepara certificados antes de subir `app` e `proxy`
- o backend aplica alteracoes de schema automaticamente na inicializacao
- o `db-restore` importa o backup mais recente apenas quando o banco estiver vazio
- `update.sh` executa `git pull` e `docker compose up -d --build`

Para forcar reemissao dos certificados, use:

```bash
RB_CERT_FORCE_REISSUE=1 docker compose up -d --build cert-bootstrap app proxy
```

## Atualizar do GitHub

```bash
./update.sh
```

Ou para outra branch:

```bash
./update.sh nome-da-branch
```

Quando a atualizacao precisar evitar subir `db-restore`:

```bash
git pull --ff-only origin main
docker compose up -d --build --no-deps app proxy
```

Observacao:

- isso evita acionar `db-restore`, mas o backend ainda executa `ensure_schema()` no startup

## Portal de docs

O backend tambem serve a documentacao HTML local do projeto:

- `/docs`
- `/docs/`
- `/docs/index.html`
- `/docs/documentacao.html`
- `/docs/diagramas.html`

Os redirects do Nginx foram ajustados para preservar host e porta customizada ao abrir `/docs`.

## Sincronizacao producao -> homologacao

Para alinhar homologacao com o estado atual da producao existe o script:

```bash
./deploy/sync-production-to-homolog.sh
```

Resumo do fluxo:

- exige `RB_CERT_BOOTSTRAP=0` na homologacao
- pode atualizar codigo, banco e volumes conforme `RB_SYNC_*`
- gera backups locais em `sync-backups/`
- baixa o dump de producao via `/api/backup`
- volta a subir `app` e `proxy` no final

## O que fica persistido

- Banco MySQL no volume `db_data`
- Fotos e arquivos da aplicacao no volume `app_data`
- Banco SQLite e segmentos das cameras no volume `cameras_data`
- Backups SQL em `backups sql/`
- CA e certificados emitidos em `certs/`
- Backups de sync em `sync-backups/`
- Snapshots operacionais versionados em `sync-import/`

Isso permite fazer `git pull` e rebuild sem perder os dados.
