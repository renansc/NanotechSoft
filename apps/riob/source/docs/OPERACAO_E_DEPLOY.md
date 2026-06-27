# Operacao e Deploy do Sistema RioBranco

## 1. Objetivo

Este documento descreve como subir, atualizar, validar e operar o sistema em ambientes como producao e homologacao.

Ele foi escrito para manter o deploy o mais automatico possivel, com foco em:

- bootstrap automatico de banco, certificados e app
- restauracao automatica de backup quando aplicavel
- minimizacao de passos manuais em clientes SIP/WebRTC
- padronizacao entre VMs

## 2. Topologia operacional

```mermaid
flowchart LR
    U[Usuarios] --> P[Nginx proxy]
    P --> A[Flask app]
    U --> W[Open WebUI]
    W --> O[Ollama / Qwen]
    A --> O
    A --> DB[(MariaDB)]
    A --> PBX[FreePBX]
    A --> M1[Monitor ESXi]
    A --> M2[Monitor Cameras]
    A --> M3[Monitor Automacao]
    A --> FS[Volumes persistentes]
    C[cert-bootstrap] --> P
    C --> PBX
    R[db-restore] --> DB
```

## 3. Pre-requisitos

### Host

- Docker e Docker Compose operacionais
- conectividade de rede entre a VM do app e o FreePBX
- portas publicadas livres
- armazenamento persistente para volumes

### Dependencias externas

- FreePBX/Asterisk acessivel por SSH
- WSS/HTTP do FreePBX habilitado
- tronco SIP funcional no FreePBX para chamadas externas
- ESXi/vCenter acessivel, se o monitor for usado
- projeto do monitor industrial disponivel no caminho de `RB_AUTOMACAO_MONITOR_PATH`

## 4. Arquivos e diretorios importantes

- `.env`
- `.env.example`
- `docker-compose.yml`
- `deploy/db/restore-latest-backup.sh`
- `deploy/lib/ollama.sh`
- `deploy/ollama/pull-model.sh`
- `deploy/sync-production-to-homolog.sh`
- `deploy/certs/bootstrap_trust.py`
- `deploy/nginx/http.conf.template`
- `deploy/nginx/https.conf.template`
- `docs/index.html`
- `certs/`
- `backupsSql/`
- `Relatorios/`
- `nfe-cache/`
- `sync-import/`

Observacao adicional:

- o OCR de DANFE por foto depende das dependencias `Pillow`, `pytesseract`, `tesseract-ocr` e `tesseract-ocr-por` estarem presentes na imagem do `app`
- o OCR focado nos itens tambem depende de `rapidocr` e `onnxruntime`; na primeira execucao o motor pode baixar modelos para o container
- a alternativa em nuvem usa `Azure Document Intelligence`; configure endpoint, chave, modelo e versao da API em `Config > NF-e` antes de usar o botao de leitura dos itens via Azure
- para OCR de fotos grandes, o proxy usa timeouts maiores; depois de alterar os templates do Nginx, recrie pelo menos `proxy`
- o monitor de cameras foi reorganizado para operacao desktop: grid lateral de cameras clicaveis e player dominante na largura restante da tela
- o cadastro de novas cameras fica em `Config > Cameras`; o monitor ficou focado em visualizacao e playback
- o menu `Monitor > Automacao` integra o app industrial externo sob `/monitor/automacao/`
- no portal assistido da NF-e, a consulta publica pode abrir com a chave bipada ja na URL, reduzindo o processo operacional ao `reCAPTCHA` e ao uso do bookmarklet
- o frontend principal passou a receber `no-store/no-cache` tambem em `/`, `RioBranco.html`, `script.js` e `style.css`, diminuindo problema de cache apos deploy
- o menu `Cargas` ganhou uma view de `Escala` para ajustar equipe e acompanhar pendencias antes do carregamento
- o cadastro de motoristas passou a representar colaboradores com papeis de motorista, entregador e ajudante

## 5. Variaveis de ambiente criticas

### 5.1 Banco

- `RB_DB_NAME`
- `RB_DB_USER`
- `RB_DB_PASSWORD`
- `RB_DB_ROOT_PASSWORD`
- `RB_DB_BACKUP_PATH`
- `RB_DB_RESTORE_FORCE`

### 5.2 HTTPS e certificados

- `RB_ENABLE_HTTPS`
- `RB_SERVER_NAME`
- `RB_PUBLIC_BASE_URL`
- `RB_HTTP_PORT`
- `RB_HTTPS_PORT`
- `RB_CERT_BOOTSTRAP`
- `RB_CA_CERT_CN`
- `RB_CA_CERT_DAYS`
- `RB_SERVER_CERT_DAYS`
- `RB_CERT_FORCE_REISSUE`
- `RB_CERT_APP_HOSTS`
- `RB_CERT_PBX_HOSTS`

### 5.3 FreePBX

- `RB_FREEPBX_HOST`
- `RB_FREEPBX_SSH_PORT`
- `RB_FREEPBX_SSH_USER`
- `RB_FREEPBX_SSH_PASS`
- `RB_FREEPBX_PJSIP_TRANSPORT`
- `RB_FREEPBX_PJSIP_ALLOW`

### 5.4 Agent IA / Ollama

- `RB_AGENT_LLM_PROVIDER`
- `RB_MANAGED_OLLAMA`
- `RB_MANAGED_OLLAMA_MODEL`
- `RB_OLLAMA_REMOVE_MODELS`
- `RB_OLLAMA_IMAGE`
- `RB_OLLAMA_BIND`
- `RB_OLLAMA_PORT`
- `RB_AGENT_OLLAMA_URL`
- `RB_AGENT_OLLAMA_MODEL`
- `RB_AGENT_OLLAMA_TIMEOUT`
- `RB_AGENT_OLLAMA_TEMPERATURE`

### 5.5 Open WebUI

- `RB_OPEN_WEBUI_IMAGE`
- `RB_OPEN_WEBUI_PORT`
- `RB_OPEN_WEBUI_NAME`
- `RB_OPEN_WEBUI_SECRET_KEY`
- `RB_OPEN_WEBUI_ENABLE_SIGNUP`
- `RB_OPEN_WEBUI_OLLAMA_URL`
- `RB_OPEN_WEBUI_VOLUME`

### 5.6 SIP frontend

- `RB_SIP_HABILITADO`
- `RB_SIP_MODO_ATIVO`
- `RB_SIP_FREEPBX_WS_URL`
- `RB_SIP_FREEPBX_DOMINIO`
- `RB_SIP_FREEPBX_REGISTRAR_SERVER`

### 5.7 Monitores

- `ESXI_HOST`
- `ESXI_USER`
- `ESXI_PASS`
- `ESXI_SSH_PORT`
- `RB_VSPHERE_CLIENT_PATH`
- `RB_AUTOMACAO_MONITOR_PATH`

### 5.8 Sincronizacao producao para homologacao

- `RB_SYNC_PROD_BASE_URL`
- `RB_SYNC_PROD_HOST`
- `RB_SYNC_PROD_SSH_USER`
- `RB_SYNC_PROD_SSH_KEY`
- `RB_SYNC_BRANCH`
- `RB_SYNC_CODE`
- `RB_SYNC_DB`
- `RB_SYNC_APP_DATA`
- `RB_SYNC_CAMERAS_DATA`
- `RB_SYNC_CURL_INSECURE`
- `RB_SYNC_BACKUP_DIR`

### 5.9 Importacao automatica de XML por e-mail

- `RB_EMAIL_AUTO_IMPORT`
- `RB_EMAIL_AUTO_INTERVAL_MINUTES`
- `RB_EMAIL_BUSINESS_START`
- `RB_EMAIL_BUSINESS_END`
- `RB_EMAIL_BUSINESS_DAYS`
- `RB_EMAIL_XML_MAX_FILE_MB`
- `RB_EMAIL_XML_ZIP_MAX_ENTRIES`
- `RB_EMAIL_XML_ZIP_MAX_TOTAL_MB`
- `RB_EMAIL_XML_TRUSTED_SENDERS`
- `RB_EMAIL_XML_TRUSTED_ZIP_MAX_ENTRIES`
- `RB_EMAIL_XML_LOCAL_BACKLOG_MAX_ATTACHMENTS`

O remetente `bebidasriobranco8@gmail.com` e confiavel por padrao para remessas
ZIP com ate `1000` XMLs. Antes de consultar o POP3, cada ciclo tambem
reprocessa anexos XML/ZIP salvos localmente que ainda nao possuem importacao
concluida. A deduplicacao continua sendo feita pela chave da NF-e e pelo hash
do conteudo.

## 6. Padrao de `.env`

### 6.1 Producao oficial

Use este modelo na VM que e dona do certificado WSS do FreePBX:

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
RB_FREEPBX_SSH_PASS=troque-esta-senha
```

### 6.2 Homologacao ou VM secundaria

Use este modelo quando a VM apontar para o mesmo FreePBX da producao:

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
RB_FREEPBX_SSH_PASS=troque-esta-senha
```

Regra critica:

- so uma VM deve usar `RB_CERT_BOOTSTRAP=1` para o mesmo FreePBX
- todas as VMs ainda emitem seu proprio certificado HTTPS para `RB_SERVER_NAME`

## 7. Fluxo de deploy

```mermaid
flowchart TD
    A[git pull ou checkout novo] --> B[docker compose up -d --build]
    B --> C[db sobe]
    C --> D[db-restore verifica backup]
    D --> E[cert-bootstrap emite CA e certificados]
    E --> F[cert-bootstrap instala WSS no FreePBX]
    F --> G[Ollama sobe]
    G --> H[ollama-model-init garante Qwen]
    H --> I[Open WebUI sobe com Qwen padrao]
    H --> J[app sobe]
    J --> K[ensure_schema atualiza schema]
    K --> L[proxy sobe]
    I --> M[sistema pronto]
    L --> M
```

## 8. Primeira subida

### 8.1 Preparacao

1. Copie `.env.example` para `.env`.
2. Ajuste senhas e IPs.
3. Confirme o papel da VM:
   - producao oficial: `RB_CERT_BOOTSTRAP=1`
   - secundaria/homologacao: `RB_CERT_BOOTSTRAP=0`
4. Gere `RB_OPEN_WEBUI_SECRET_KEY`:

```bash
openssl rand -hex 32
```

### 8.2 Comando

```bash
docker compose up -d --build
```

### 8.3 Validacao inicial

```bash
docker compose ps
docker compose logs --tail=200 cert-bootstrap
docker compose logs --tail=200 ollama-model-init
docker compose logs --tail=200 open-webui
docker compose logs --tail=200 app
docker compose logs --tail=200 proxy
```

Checklist:

- `db` deve estar `healthy`
- `db-restore` deve concluir com sucesso ou pular restauracao
- `cert-bootstrap` deve concluir com sucesso ou sair rapidamente quando desabilitado
- `ollama` deve estar `healthy`
- `ollama-model-init` deve concluir depois de instalar ou confirmar o Qwen
- `open-webui` deve estar `healthy` e listar `qwen2.5:3b`
- `app` deve subir sem erro de schema
- `proxy` deve publicar as portas esperadas

## 9. Atualizacao de codigo

### 9.1 Fluxo padrao

```bash
./update.sh
```

Equivalente manual:

```bash
git pull --ff-only origin main
docker compose up -d --build
```

### 9.2 Quando usar reemissao forcada de certificados

Use somente quando houver troca de IP, DNS, CA ou problema real de certificado:

```bash
RB_CERT_FORCE_REISSUE=1 docker compose up -d --build cert-bootstrap app proxy
```

### 9.3 Atualizacao de app/proxy sem acionar restore

Quando a necessidade for atualizar apenas codigo e interface, mantendo `db` e `db-restore` fora do ciclo:

```bash
git pull --ff-only origin main
docker compose up -d --build --no-deps app proxy
```

Observacao importante:

- quando a atualizacao envolver apenas monitor de cameras, portal assistido da NF-e ou telas do frontend, `docker compose up -d --build --no-deps app proxy` costuma ser suficiente

- isso evita subir `db-restore`, mas o backend ainda executa `ensure_schema()` ao inicializar

- a antiga migração `usuarios -> colaboradores` ja foi executada em producao e nao roda mais no fluxo de atualizacao

### 9.4 Validacao rapida em homologacao para chat, SIP e vendas

Quando a mudanca for apenas de interface/backend do app:

```bash
docker compose up -d --build app proxy
docker compose logs --tail=150 app
```

Checklist rapido:

- abrir `Config -> Vendas`
- usar `Importar relatorio CSV` para subir um arquivo manualmente ou `Importar do diretorio` para usar o CSV detectado no servidor
- confirmar que o arquivo entrou na lista de caches
- marcar no checkbox qual relatorio deve ficar `Em uso`
- abrir `Vendas -> Relatorio` e validar totais e detalhamento por vendedor
- abrir o chat interno e validar o beep de nova mensagem
- validar chamada SIP de saida e entrada para confirmar tom de discagem e toque de chamada

Observacao:

- navegadores podem exigir uma interacao previa do usuario na pagina antes de liberar audio

## 10. Volumes e persistencia

Persistencia principal:

- `db_data`
  - MariaDB
- `app_data`
  - anexos do chat, fotos, requisicoes, cache local de XML da NF-e, uploads manuais do modulo de vendas e SQLite do monitor de automacao

### 10.1 Importacao persistida de vendas

O modulo `Vendas -> Relatorio` importa o CSV para o MariaDB para evitar reler o arquivo bruto inteiro a cada consulta.

Diretorios/arquivos relevantes:

- `Relatorios/`
  - origem atual do CSV externo
  - precisa estar montada em `/app/Relatorios` no container `app` para o botao `Importar do diretorio` enxergar o arquivo atual
  - contem tambem o arquivo `config-rel-vendas`, com as regras operacionais da importacao do CSV

- `DATA_ROOT/vendas-cache/`
  - uploads manuais do CSV feitos pela tela `Config -> Vendas`

- `DATA_ROOT/vendas-config.json`
  - configuracao da fonte do modulo de vendas

- tabela `vendas_relatorios_importados`
  - lista dos relatorios importados, status e qual esta ativo

- tabela `vendas_relatorio_itens`
  - linhas importadas do relatorio para consulta por vendedor e por total, com agrupadores por cidade e por produto

Fluxo atual:

1. o operador aponta a origem em `Config -> Vendas`
2. pode importar um CSV manualmente pelo botao `Importar relatorio CSV` ou usar `Importar do diretorio`
3. cada importacao entra na lista de relatorios importados
4. um checkbox define qual relatorio importado esta `Em uso`
5. o relatorio de vendas passa a ler somente o import ativo salvo no banco
6. a tela de `Vendas -> Relatorio` exibe totais por vendedor, cidade e produto
7. ao excluir um relatorio importado, o sistema remove o registro e as linhas dele do banco

Regras de importacao:

1. o backend le `Relatorios/config-rel-vendas` para descobrir os grupos normalizados e os registros que devem ser descartados
2. as regras entram na assinatura do cache, entao alterar esse arquivo exige nova importacao/processamento para refletir no sistema
3. o import usa apenas as colunas necessarias do CSV e ignora colunas extras listadas nesse arquivo
4. se uma coluna aparecer ao mesmo tempo como necessaria e como descartada, a regra de descarte tem prioridade

- `app_data`
  - dados persistentes da aplicacao

- `cameras_data`
  - banco SQLite e segmentos HLS gerados pelo monitor de cameras

- `ollama_data`
  - modelos gerenciados pelo Ollama, incluindo `qwen2.5:3b`

- `open_webui_data`
  - usuarios, conversas, configuracoes e cache do Open WebUI

Observacao de backup:

- o backup completo atual cobre banco, `app_data`, `cameras_data` e `Relatorios/`
- `ollama_data` pode ser recriado pelo `ollama-model-init`
- `open_webui_data` exige backup separado quando for necessario preservar usuarios e conversas

Persistencia por bind mount:

- `backupsSql/`
  - dumps SQL

- `certs/`
  - CA e certificados emitidos

- `esxi/`
  - monitor ESXi versionado

- caminho de `RB_AUTOMACAO_MONITOR_PATH`
  - codigo externo do monitor industrial montado somente para leitura em `/opt/automacao-monitor`

- `sync-backups/`
  - backups locais gerados antes da sincronizacao producao -> homologacao

- `sync-import/`
  - snapshots versionados de SQL e dados importados manualmente para referencia operacional

## 11. Backup e restore

### 11.1 Geracao de backup

Pelo frontend:

- `Config` -> gerar backup SQL
- `Config` -> gerar backup completo

Pela API:

```bash
curl -k -O https://HOST:PORT/api/backup
```

Comportamento:

- o backend executa `mariadb-dump --skip-ssl`
- salva o dump em `backupsSql/backup_YYYYMMDD_HHMMSS.sql`
- devolve o mesmo arquivo no download HTTP

Esse backup SQL e indicado para:

- restore automatico do banco pelo container `db-restore`
- sincronizacao producao -> homologacao
- copia rapida somente do MariaDB

### 11.1.1 Backup completo para recuperar outro ambiente

Para migrar ou recuperar uma VM inteira, use o backup completo:

```bash
curl -k -O https://HOST:PORT/api/backup/full
```

Ou pelo assistente local:

```bash
./riob-agent.sh full-backup
```

Comportamento:

- gera `backupsSql/backup_full_YYYYMMDD_HHMMSS.tar.gz`
- inclui `manifest.json`
- inclui `db/backup.sql` com tabelas, dados, triggers, eventos e rotinas
- inclui `app_data`, com fotos de devolucoes, requisicoes PDF, anexos do chat, XML/cache de NF-e, uploads/cache de vendas, configuracoes locais e o SQLite do monitor de automacao
- inclui `cameras_data`, com cadastro/banco local do monitor de cameras e dados persistidos no volume
- inclui `relatorios`, com a origem local dos CSVs e `config-rel-vendas`

Por seguranca, o pacote completo nao inclui `.env`, certificados privados, senhas externas de infraestrutura nem chaves SSH. Em outro ambiente, configure `.env` e certificados antes ou depois do restore conforme a necessidade operacional.

Chaves privadas SSH, arquivos `*.key`, `*.p12` e `*.pfx` tambem nao devem ser
versionados. Use secrets externos ou arquivos locais protegidos.

Restore em ambiente novo:

```bash
git clone <repo> riob
cd riob
cp .env.example .env
# ajuste senhas, IPs, portas e RB_CERT_BOOTSTRAP conforme o papel da VM
./deploy/restore-full-backup.sh backupsSql/backup_full_YYYYMMDD_HHMMSS.tar.gz --yes
docker compose up -d --build app proxy
```

Use o restore completo somente em ambiente novo ou depois de gerar backup local do ambiente atual, porque ele substitui banco, `app_data`, `cameras_data` e `Relatorios/`.

### 11.2 Restore automatico

O container `db-restore`:

- localiza o backup mais recente em `backupsSql/`
- verifica se o banco esta vazio
- importa o arquivo automaticamente apenas quando o banco estiver vazio

Para forcar:

```bash
RB_DB_RESTORE_FORCE=1 docker compose up db-restore
```

### 11.3 O que nunca fazer sem necessidade

- nao usar `docker compose down -v`
- nao apagar `db_data`
- nao limpar `backupsSql/` sem politica definida

### 11.4 Sincronizacao producao -> homologacao

O projeto possui um fluxo assistido para alinhar homologacao com o estado atual da producao:

```bash
./deploy/sync-production-to-homolog.sh
```

Comportamento:

- valida que a homologacao esta com `RB_CERT_BOOTSTRAP=0`
- opcionalmente atualiza o codigo local pela branch configurada
- para `app` e `proxy` antes da sincronizacao
- gera backup local do banco da homologacao em `sync-backups/`
- baixa o dump atual da producao via `/api/backup`
- apos importar o banco, redefine `nfe_config` para defaults seguros de homologacao por padrao:
- `habilitado=0`
- `ambiente=homologacao`
- `ultimo_nsu=''`
- `auto_manifestar_ciencia=0`
- opcionalmente sincroniza os volumes `/data/app` e `/data/cameras`
- sobe novamente `app` e `proxy`

Cuidados:

- revisar `RB_SYNC_*` no `.env` antes de usar
- se realmente precisar preservar a configuracao NF-e clonada da producao, usar `RB_SYNC_RESET_NFE_CONFIG=0`
- usar chave SSH quando necessario via `RB_SYNC_PROD_SSH_KEY`
- tratar `sync-import/` como artefato de referencia, nao como volume automatico do deploy

## 12. Certificados e onboarding de clientes

## 12.1 Estrategia atual

O sistema foi padronizado para usar:

- uma CA interna
- certificado HTTPS da aplicacao assinado por essa CA
- certificado WSS do FreePBX assinado pela mesma CA

Objetivo:

- reduzir downloads manuais
- permitir que clientes confiem em uma unica CA

## 12.2 Endpoints de distribuicao

- `/api/ca/cert.pem`
- `/api/ca/cert.crt`
- `/api/sip/windows-install.ps1`
- `/api/sip/linux-install.sh`
- `/api/sip/apple.mobileconfig`
- `/api/certs.p12`
- `/api/certs.pfx`

## 12.3 Comportamento do Nginx

Mesmo quando o cliente ainda nao confia no `8443`, o proxy permite baixar os arquivos de onboarding por HTTP nas rotas de certificados e scripts antes do redirect completo para HTTPS.

Atualizacao recente:

- `/docs` e `/docs/` redirecionam para `/docs/index.html` preservando host e porta customizada

## 12.4 Regra pratica por plataforma

- Windows:
  - preferir o script PowerShell

- Linux desktop:
  - preferir o script shell

- iPhone/iPad:
  - preferir o `.mobileconfig`

- Android:
  - preferir o `.crt` da CA

## 13. Operacao de SIP e FreePBX

### 13.1 Bootstrap de usuario SIP

Ao criar, editar ou logar um usuario:

- o backend define ou corrige `sip_usuario`, `sip_ramal` e `sip_senha`
- depois tenta sincronizar o ramal no FreePBX

### 13.2 Regras de negocio

- `sip_ramal` e o ramal interno de 4 digitos
- `sip_usuario` e o identificador de autenticacao SIP
- `sip_senha` e a senha usada no softphone/browser
- `usuarios.senha` e o hash da senha do sistema, nao deve ser usada como senha SIP
- `sip_habilitado=1` libera chamadas externas

### 13.3 Validacoes importantes

```bash
docker compose exec app env | grep RB_FREEPBX
curl -k https://HOST:PORT/api/status
```

No FreePBX:

```bash
asterisk -rx "http show status"
asterisk -rx "pjsip show endpoints"
asterisk -rx "pjsip show contacts"
```

## 13.4 NF-e / Receita

Para o passo a passo detalhado da integracao operacional de NF-e / Receita, consulte:

- `NFE_RECEITA_E_INTEGRACAO.md`

Regra pratica importante:

- o fluxo atual recomendado continua baseado no XML oficial da NF-e
- o modo `portal_assistido` abre a consulta oficial e apoia o operador
- o modo `certificado_digital` hoje registra configuracao, mas nao executa download automatico no backend

## 14. Runbook de verificacao rapida

### 14.1 Estado geral

```bash
docker compose ps
curl -k https://HOST:PORT/api/status
curl -k https://HOST:PORT/docs/index.html
```

### 14.2 Logs

```bash
docker compose logs --tail=200 app
docker compose logs --tail=200 proxy
docker compose logs --tail=200 cert-bootstrap
docker compose logs --tail=200 db
docker compose logs --tail=200 ollama
docker compose logs --tail=200 open-webui
```

### 14.3 Validacao de HTTPS

```bash
curl -vk https://HOST:PORT/
openssl s_client -connect HOST:PORT -servername HOST </dev/null
```

### 14.4 Validacao de WSS do FreePBX

```bash
openssl s_client -connect PBX:8089 -servername PBX </dev/null
```

## 15. Troubleshooting

### 15.1 `https://IP-DA-VM` nao abre

Verifique:

- `RB_ENABLE_HTTPS=1`
- `proxy` em execucao
- arquivos em `certs/fullchain.pem` e `certs/privkey.pem`
- logs do `proxy`
- se o navegador confia na CA interna do RioBranco

Na producao, baixe a CA sem depender do HTTPS:

```text
http://192.168.200.254/api/ca/cert.crt
```

No Windows, instale o arquivo em `Autoridades de Certificacao Raiz Confiaveis`.
Em um PowerShell executado como administrador:

```powershell
certutil -addstore -f Root .\riobranco-ca.crt
```

Depois feche e abra novamente o navegador e acesse:

```text
https://192.168.200.254
```

### 15.2 `Cliente web: SIP desconectado do servidor`

Causas comuns:

- cliente nao confia na CA
- WSS do FreePBX inacessivel
- certificado do FreePBX nao bate com host/IP

Validar:

- `/api/ca/cert.pem`
- `asterisk -rx "http show status"`
- `openssl s_client -connect PBX:8089 -servername PBX`

### 15.3 `Falha no registro SIP: Rejected`

Causas comuns:

- `sip_ramal`, `sip_usuario` ou `sip_senha` divergentes entre app e FreePBX
- extensao antiga conflitante

Validar:

- cadastro do usuario na app
- `POST /api/sip/freepbx/sync`
- `pjsip show endpoint <ramal>`

### 15.4 Falha ao sincronizar ramais

Causas comuns:

- `RB_FREEPBX_SSH_USER` ou `RB_FREEPBX_SSH_PASS` vazios
- SSH bloqueado
- senha SIP do usuario ausente

### 15.5 Erro de backup SQL com SSL

O sistema ja usa `mariadb-dump --skip-ssl`.

Se ainda houver erro:

- confirmar se o container `app` foi recriado com codigo atualizado
- validar logs do endpoint `/api/backup`

### 15.6 Restore nao aconteceu

Validar:

- existencia de arquivo em `backupsSql/`
- banco realmente vazio
- logs de `db-restore`
- `RB_DB_RESTORE_FORCE`

### 15.7 Portal `/docs` abre em host ou porta errados

Validar:

- `deploy/nginx/http.conf.template` e `deploy/nginx/https.conf.template` atualizados
- acesso por `/docs/index.html`
- se ha proxy externo sobrescrevendo `Host`

## 16. Rotina operacional recomendada

### Diariamente

- validar `api/status`
- acompanhar se o proxy e app estao de pe

### Semanalmente

- gerar e copiar backup SQL
- conferir espaco em disco
- revisar logs de exclusao e falhas SIP

### Em alteracao de rede/IP

- revisar `.env`
- reemitir certificados somente se necessario
- confirmar onboarding dos clientes

### Durante a operacao do patio

Kanban operacional:

- abrir `Dashboard -> Resumo` em `RioBranco.html`
- mover cada frete para a coluna que representa o estagio real da operacao
- revisar diariamente cards presos em `paradoVasio`, `paradoCarregado` e `carregando`
- usar os campos do proprio card para manter nome, veiculo, motorista, carga e observacao atualizados

Modo TV com `dashboards.html`:

- abrir `https://HOST:PORT/dashboards.html` na TV, monitor da expedicao ou tela dedicada
- manter o navegador em tela cheia para acompanhamento continuo
- validar se a rotacao entre `Resumo` e `Frota / Manutencao` esta acontecendo
- usar `RioBranco.html` para operar; `dashboards.html` nao substitui a tela principal

## 17. Recomendacoes de seguranca

- nao manter senhas reais versionadas
- limitar acesso SSH ao FreePBX
- proteger a aplicacao com rede interna ou controle adicional
- usar uma chave aleatoria longa em `RB_OPEN_WEBUI_SECRET_KEY`
- desativar `RB_OPEN_WEBUI_ENABLE_SIGNUP` depois de criar a conta administradora
- revisar o uso de `localStorage` para sessao
- manter os certificados e chaves privados apenas no servidor

## 18. Resumo operacional

O deploy padrao correto e:

```bash
git pull origin main
docker compose up -d --build
```

O sistema foi preparado para que esse fluxo:

- atualize o codigo
- mantenha os dados persistentes
- reaplique schema
- restaure backup apenas quando o banco estiver vazio
- mantenha onboarding de certificados padronizado
- mantenha Ollama/Qwen e Open WebUI no mesmo compose oficial

O principal cuidado para ambientes multiplos continua sendo:

- apenas uma VM deve controlar o certificado WSS do mesmo FreePBX

## 19. Agent IA no navegador

O sistema principal tem um menu `Agent IA` em `RioBranco.html`.
A conversa fica preservada no navegador entre recargas, para manter contexto de uso.
Tambem existe um atalho `Agent IA` no chat de `Comunicacao`, para abrir o painel sem
sair do fluxo principal.

Ali voce pode:

- conversar com o assistente em portugues
- pedir explicacao de rotinas do sistema
- analisar um pedido antes de editar
- validar baseline rapido
- listar cargas do kanban
- mover fretes entre status
- executar backup, deploy, update, logs e diagnostico

Se o Ollama estiver disponivel, o chat usa o modelo configurado em `RB_AGENT_OLLAMA_MODEL`.
Se o modelo nao estiver acessivel, o sistema cai para o agente local existente, sem bloquear o uso da interface.

Exemplo de configuracao:

```env
RB_AGENT_LLM_PROVIDER=auto
RB_MANAGED_OLLAMA=1
RB_MANAGED_OLLAMA_MODEL=qwen2.5:3b
RB_OLLAMA_REMOVE_MODELS=qwen2.5:7b
RB_OLLAMA_IMAGE=ollama/ollama:latest
RB_OLLAMA_BIND=127.0.0.1
RB_OLLAMA_PORT=11434
RB_AGENT_OLLAMA_URL=http://ollama:11434
RB_AGENT_OLLAMA_MODEL=qwen2.5:3b
RB_OPEN_WEBUI_IMAGE=ghcr.io/open-webui/open-webui:v0.9.6
RB_OPEN_WEBUI_COMPAT_IMAGE=riob-open-webui:v0.9.6-numpy2.2.6
RB_OPEN_WEBUI_NUMPY_VERSION=2.2.6
RB_OPEN_WEBUI_PORT=3000
RB_OPEN_WEBUI_NAME=RioBranco IA
RB_OPEN_WEBUI_SECRET_KEY=gere-com-openssl-rand-hex-32
RB_OPEN_WEBUI_ENABLE_SIGNUP=true
RB_OPEN_WEBUI_OFFLINE_MODE=true
RB_OPEN_WEBUI_HF_HUB_OFFLINE=1
RB_OPEN_WEBUI_OLLAMA_URL=http://ollama:11434
```

Em deploy Docker, o projeto sobe um container `riobranco-ollama` com volume
persistente `ollama_data` e um container `riobranco-open-webui` com volume
persistente `open_webui_data`. Os scripts `./up.sh` e `./update.sh` executam o
bootstrap `ollama-model-init`, que faz `ollama pull` do modelo definido em
`RB_AGENT_OLLAMA_MODEL`, sobem o WebUI e validam que ele consegue listar esse
mesmo modelo. A logica comum dos atalhos fica em `deploy/lib/ollama.sh`; o pull
do modelo fica em `deploy/ollama/pull-model.sh`.

O Open WebUI e construido sobre a imagem oficial definida em
`RB_OPEN_WEBUI_IMAGE`, com NumPy `2.2.6` fixado por
`RB_OPEN_WEBUI_NUMPY_VERSION`. Isso preserva compatibilidade com o Xeon E5410
de producao, que nao oferece todas as instrucoes exigidas por `x86-64-v2`.

Por padrao, `RB_OPEN_WEBUI_OFFLINE_MODE=true` e
`RB_OPEN_WEBUI_HF_HUB_OFFLINE=1` evitam downloads de modelos auxiliares no
startup. Isso nao afeta o chat com o Qwen. RAG, documentos e transcricao
precisam de modelos locais adicionais caso esses recursos sejam habilitados.

Para producao usando o Ollama gerenciado pelo compose:

1. mantenha `RB_MANAGED_OLLAMA=1`
2. deixe `RB_AGENT_OLLAMA_URL=http://ollama:11434`
3. defina `RB_AGENT_OLLAMA_MODEL` com o mesmo Qwen validado na homologacao
4. deixe `RB_OPEN_WEBUI_OLLAMA_URL=http://ollama:11434`
5. gere uma chave longa para `RB_OPEN_WEBUI_SECRET_KEY`
6. execute `./update.sh`

No modo gerenciado, `RB_MANAGED_OLLAMA_MODEL` define o modelo oficial e assume
`qwen2.5:3b` quando nao estiver presente. Depois do pull e da validacao, o
bootstrap remove os modelos listados em `RB_OLLAMA_REMOVE_MODELS`; o padrao
remove `qwen2.5:7b`.

O proxy e o Open WebUI sao publicados em todas as interfaces da VM. Os scripts
`./up.sh` e `./update.sh` validam `/api/status` pelo valor de
`RB_PUBLIC_BASE_URL`, impedindo que um deploy aparentemente saudavel fique
acessivel apenas por `localhost`.

Se for necessario usar um Ollama externo, defina `RB_MANAGED_OLLAMA=0` e informe
`RB_AGENT_OLLAMA_URL`; nesse modo o deploy nao instala modelo no servidor externo,
mas a validacao final ainda falha se o modelo configurado nao estiver acessivel.

O Open WebUI fica disponivel por padrao em `http://IP-DA-VM:3000`. A primeira
conta cadastrada se torna administradora. Depois do primeiro cadastro, defina
`RB_OPEN_WEBUI_ENABLE_SIGNUP=false` e execute `./update.sh` para bloquear novos
registros publicos.

Nao mantenha uma segunda instalacao nativa do Ollama nem outro compose separado
do Open WebUI na mesma VM. O deploy oficial passa a administrar ambos pelo
`docker-compose.yml` deste repositorio.

## 20. Migracao dos combustiveis da frota

O cadastro de cada veiculo define o diesel padrao: `diesel_s10` ou
`diesel_500`. Veiculos Diesel S10 tambem permitem lancamentos de Arla; veiculos
Diesel 500 nao permitem Arla.

Para classificar o cadastro e os lancamentos existentes, primeiro simule:

```bash
./deploy/db/migrate-abastecimentos-combustivel.sh --dry-run
```

Depois aplique:

```bash
./deploy/db/migrate-abastecimentos-combustivel.sh
```

O script considera os veiculos `60`, `61`, `30`, `31`, `58`, `57` e `59`
como Diesel S10. Todos os demais ficam como Diesel 500. Lancamentos de Arla
sao preservados somente nos veiculos Diesel S10. O script e idempotente e pode
ser executado novamente para conferir ou reaplicar essa classificacao.

Fluxo de uso:

1. Abra `RioBranco.html`
2. Clique em `Agent IA`
3. Digite sua pergunta ou comando
4. Use os botoes sugeridos quando o sistema pedir confirmacao ou precisar de uma mensagem de commit

## 21. Revisao de abastecimentos importados por XML

Quando o contador de abastecimentos XML indicar pendencias:

1. abra `Importar XML > Abastecimentos`
2. na caixa `Pendencias de abastecimento`, clique em `Revisar`
3. selecione o veiculo e confira KM, combustivel, quantidade, valor, data e
   posto
4. clique em `Salvar e finalizar`

O sistema atualiza os dados importados e executa novamente a integracao com a
frota. A pendencia desaparece quando o vinculo passa para `criado` ou
`vinculado`. Para produtos que nao sao abastecimento, como filtros e itens de
manutencao, use `Ignorar esta pendencia` e informe o motivo. Itens ignorados nao
voltam a ser processados na sincronizacao de inicializacao.
