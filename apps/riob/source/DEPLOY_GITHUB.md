# Deploy via GitHub

## Preparacao

1. Copie `.env.example` para `.env`.
2. Ajuste as senhas do banco, `FLASK_SECRET`, `UI_*`, `ESXI_*`, `RB_FREEPBX_*` e `RB_OPEN_WEBUI_SECRET_KEY`.
3. Ajuste `RB_SERVER_NAME` e `RB_PUBLIC_BASE_URL` com o IP ou DNS real usado pelos clientes.
4. Garanta que `80`, `443` e `3000` estejam liberadas no firewall da VM.
5. Se quiser restore automatico em banco vazio, deixe o backup `.sql` ou `.sql.gz` em `backupsSql/`.
6. O monitor ESXi fica versionado em `esxi/`; altere `RB_VSPHERE_CLIENT_PATH` apenas se quiser outra copia local.
7. O monitor industrial deve ficar dentro da plataforma, em `apps/automacao/source`; altere `RB_AUTOMACAO_MONITOR_PATH` apenas se quiser outra copia local.

Na producao, o codigo de `apps/automacao/source` precisa estar atualizado com a versao que aceita
`APP_HOST`, `APP_PORT`, `APP_DEBUG`, `DATABASE_PATH` e
`X-Forwarded-Prefix`. A versao antiga inicia fixamente na porta `5000` e nao
funciona sob `/monitor/automacao/`.

No `.env` do RioBranco, quando rodar o compose interno a partir de `apps/riob/source`, o default ja aponta para a pasta interna:

```env
RB_AUTOMACAO_MONITOR_PATH=../../automacao/source
```

## Certificados e WSS

O deploy padrao agora faz isso automaticamente:

- gera uma CA interna
- gera o certificado HTTPS da aplicacao
- gera o certificado WSS do FreePBX
- instala o certificado WSS no FreePBX

O certificado HTTPS da aplicacao sempre e emitido para o IP/DNS da propria VM.
Quando varias VMs apontam para o mesmo FreePBX:

- deixe `RB_CERT_BOOTSTRAP=1` apenas na VM oficial para instalar o WSS no FreePBX
- use `RB_CERT_BOOTSTRAP=0` nas VMs secundarias para nao alterar o FreePBX

Isso nao desativa o HTTPS local; apenas evita que uma VM sobrescreva o
certificado WSS da outra.

## Exemplos de .env

Producao oficial:

```env
RB_ENABLE_HTTPS=1
RB_SERVER_NAME=192.168.200.254
RB_PUBLIC_BASE_URL=https://192.168.200.254
RB_HTTP_PORT=80
RB_HTTPS_PORT=443
RB_CERT_BOOTSTRAP=1
RB_CERT_APP_HOSTS=192.168.200.254
RB_CERT_PBX_HOSTS=192.168.200.253,freepbx.sangoma.local,localhost,127.0.0.1
RB_FREEPBX_HOST=192.168.200.253
RB_FREEPBX_SSH_PORT=22
RB_FREEPBX_SSH_USER=root
RB_FREEPBX_SSH_PASS=troque-esta-senha-freepbx
RB_MANAGED_OLLAMA=1
RB_MANAGED_OLLAMA_MODEL=qwen2.5:3b
RB_OLLAMA_REMOVE_MODELS=qwen2.5:7b
RB_AGENT_OLLAMA_MODEL=qwen2.5:3b
RB_OPEN_WEBUI_PORT=3000
RB_OPEN_WEBUI_SECRET_KEY=gere-com-openssl-rand-hex-32
```

VM secundaria ou homologacao usando o mesmo FreePBX:

```env
RB_ENABLE_HTTPS=1
RB_SERVER_NAME=192.168.200.250
RB_PUBLIC_BASE_URL=https://192.168.200.250
RB_HTTP_PORT=80
RB_HTTPS_PORT=443
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
- `ollama-model-init` baixa e valida `qwen2.5:3b` no volume persistente do Ollama
- depois da validacao, remove automaticamente o modelo antigo `qwen2.5:7b`
- `open-webui` sobe ligado diretamente ao Ollama do mesmo compose
- o backend aplica alteracoes de schema automaticamente na inicializacao
- o `db-restore` importa o backup mais recente apenas quando o banco estiver vazio
- `update.sh` executa `git pull` e `docker compose up -d --build`
- a shell do frontend recebe `no-store/no-cache`, o que ajuda a refletir mudancas de HTML, JS e CSS logo apos o rebuild

Para forcar reemissao dos certificados, use:

```bash
RB_CERT_FORCE_REISSUE=1 docker compose up -d --build cert-bootstrap app proxy
```

## Atualizar do GitHub

Os atalhos principais agora sao:

```bash
./up.sh
./down.sh
./update.sh
./riob-agent.sh
./riob-agent-web.sh
```

Uso recomendado:

- `./up.sh` sobe `app`, `proxy`, Ollama/Qwen e Open WebUI sem tocar no banco
- `./down.sh` para `app`, `proxy` e Open WebUI sem derrubar o banco ou o Ollama
- `./update.sh` faz `git pull`, garante Ollama/Qwen e Open WebUI e aplica o deploy sem acionar `db-restore`
- `./riob-agent.sh` abre um assistente para backup, Git, deploy, update, logs e diagnostico
- `./riob-agent-web.sh` abre o mesmo assistente em formato de conversa no navegador

## Assistente operacional

O assistente fica em `tools/riob_agent.py` e pode ser chamado pelo atalho da raiz:

```bash
./riob-agent.sh menu
./riob-agent.sh status
./riob-agent.sh backup
./riob-agent.sh git -m "mensagem do commit"
./riob-agent.sh ship -m "mensagem do commit"
./riob-agent.sh deploy
./riob-agent.sh update
./riob-agent.sh logs --tail 200 app proxy
./riob-agent.sh doctor
```

No sistema principal, o mesmo chat tambem aparece no menu `Agent IA` da pagina
`RioBranco.html`. Ali voce pode conversar com o assistente e, quando o Ollama
estiver configurado, o backend tenta usar o modelo definido em
`RB_AGENT_OLLAMA_MODEL` antes de cair para o agente local.

Nos deploys Docker, `./up.sh` e `./update.sh` sobem o servico
`riobranco-ollama`, executam o bootstrap `ollama-model-init` e criam
`riobranco-open-webui`. O WebUI usa `http://ollama:11434` pela rede interna do
compose e recebe o mesmo `RB_AGENT_OLLAMA_MODEL` como modelo padrao. A logica
compartilhada fica em `deploy/lib/ollama.sh`, e o pull/validacao do modelo fica
em `deploy/ollama/pull-model.sh`.

Para producao com o Qwen homologado, use:

```env
RB_MANAGED_OLLAMA=1
RB_AGENT_OLLAMA_URL=http://ollama:11434
RB_MANAGED_OLLAMA_MODEL=qwen2.5:3b
RB_OLLAMA_REMOVE_MODELS=qwen2.5:7b
RB_AGENT_OLLAMA_MODEL=qwen2.5:3b
RB_OPEN_WEBUI_IMAGE=ghcr.io/open-webui/open-webui:v0.9.6
RB_OPEN_WEBUI_COMPAT_IMAGE=riob-open-webui:v0.9.6-numpy2.2.6
RB_OPEN_WEBUI_NUMPY_VERSION=2.2.6
RB_OPEN_WEBUI_PORT=3000
RB_OPEN_WEBUI_OLLAMA_URL=http://ollama:11434
RB_OPEN_WEBUI_SECRET_KEY=gere-com-openssl-rand-hex-32
RB_OPEN_WEBUI_OFFLINE_MODE=true
RB_OPEN_WEBUI_HF_HUB_OFFLINE=1
```

No modo gerenciado, o compose usa `RB_MANAGED_OLLAMA_MODEL` e assume
`qwen2.5:3b` quando a variavel nao existe. Assim, uma `.env` antiga que ainda
tenha `RB_AGENT_OLLAMA_MODEL=qwen2.5:7b` nao impede a migracao.

O projeto cria uma imagem derivada do Open WebUI com NumPy `2.2.6`. Essa
versao evita a exigencia de CPU `x86-64-v2` introduzida pelo NumPy `2.4` e
mantem o deploy compativel com o Xeon E5410 usado em producao.

O modo offline impede downloads automaticos do Hugging Face durante o startup.
O chat com o Qwen continua funcionando normalmente. Recursos de RAG,
documentos e transcricao exigem modelos locais adicionais antes de serem
habilitados.

Gere a chave do WebUI antes do primeiro deploy:

```bash
openssl rand -hex 32
```

No primeiro acesso a `http://192.168.200.254:3000`, a primeira conta criada se torna
administradora. Depois desse cadastro, desative novos registros em `.env` com
`RB_OPEN_WEBUI_ENABLE_SIGNUP=false` e execute `./update.sh`.

O sistema principal fica em `https://192.168.200.254`. O compose publica o
proxy e o Open WebUI em `0.0.0.0`; `./up.sh` e `./update.sh` falham quando
`/api/status` nao responde pelo IP configurado. Em hosts com UFW ativo:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 3000/tcp
```

Como o HTTPS usa uma CA interna, cada computador cliente deve confiar nela.
Baixe `http://192.168.200.254/api/ca/cert.crt` e instale o certificado em
`Autoridades de Certificacao Raiz Confiaveis` antes de acessar
`https://192.168.200.254`.

Tambem existe um app independente em HTML, servido localmente por Python:

```bash
./riob-agent-web.sh --host 0.0.0.0 --port 8765
```

Depois abra:

```text
http://IP-DA-VM:8765/
```

No app web, o operador pode perguntar em formato de conversa:

- `o que faz backup?`
- `executar status`
- `enviar para o git`
- `o que faz deploy?`
- `ver logs`
- `listar cargas`
- `mostrar caminhao 13`
- `mover status para carregado caminhao 13`

O app explica cada opcao e, quando a acao altera o sistema, pede confirmacao no navegador.
Na area `Kanban / Cargas`, os cards do frete aparecem acima da conversa; ao selecionar
um card, ele fica destacado e mostra botoes para mover o status.

Fluxos recomendados:

- antes de publicar uma mudanca local: `./riob-agent.sh ship -m "descricao curta"`
- apenas gerar backup SQL: `./riob-agent.sh backup`
- gerar pacote completo para recuperar em outra VM: `./riob-agent.sh full-backup`
- apenas subir app/proxy apos ajuste local: `./riob-agent.sh deploy`
- atualizar uma VM a partir do GitHub: `./riob-agent.sh update`

Por seguranca, o comando de Git nao adiciona `.env`, `.env.backup.*`, backups SQL,
certificados, relatorios, configuracao/dados locais de camera e outros arquivos de
runtime. Se algum desses arquivos ja estiver staged, o assistente aborta antes do commit.

Se quiser seguir o fluxo manual:

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
- `./up.sh` e `./update.sh` tambem executam a reconciliacao idempotente dos
  XMLs de saida: vinculam o veiculo, reaproveitam um frete ativo ou criam um
  card aberto no Kanban, sem contabilizar o estoque

Para conferir o resultado sem persistir alteracoes:

```bash
./deploy/db/migrate-xml-fretes.sh --dry-run
```

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
- Fotos, arquivos da aplicacao e SQLite do monitor de automacao no volume `app_data`
- Banco SQLite e segmentos das cameras no volume `cameras_data`
- Modelos do Ollama, incluindo Qwen, no volume `ollama_data`
- Usuarios, conversas e configuracoes do Open WebUI no volume `open_webui_data`
- Backups SQL em `backupsSql/`
- CA e certificados emitidos em `certs/`
- Backups de sync em `sync-backups/`
- Snapshots operacionais versionados em `sync-import/`

Isso permite fazer `git pull` e rebuild sem perder os dados.

O codigo do monitor de automacao fica dentro desta plataforma em `apps/automacao/source`.
O caminho configurado em `RB_AUTOMACAO_MONITOR_PATH` precisa existir no host antes do
`docker compose up`.

Para recuperar outro ambiente, o backup SQL isolado nao basta. Gere um pacote completo com:

```bash
./riob-agent.sh full-backup
```

Esse pacote inclui `db/backup.sql`, `app_data`, `cameras_data`, `Relatorios/` e um
`manifest.json`. No destino, apos configurar `.env`, restaure com:

```bash
./deploy/restore-full-backup.sh backupsSql/backup_full_YYYYMMDD_HHMMSS.tar.gz --yes
```

O pacote completo atual nao inclui `ollama_data` nem `open_webui_data`. O Qwen
pode ser baixado novamente pelo `ollama-model-init`; para preservar usuarios e
conversas do Open WebUI, faca backup separado do volume `open_webui_data`.
