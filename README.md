# NanotechSoft

Portal Flask + MySQL para centralizar apps instalados dinamicamente.

## Acesso inicial

- Usuario: `admin`
- Senha: `admin`

No primeiro acesso o sistema cria o banco `notechsoft`, as tabelas base e o usuario admin.

## Rodar localmente

```bash
cd NanotechSoft
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Abra `http://127.0.0.1:5600`.

## Bancos com Docker

```bash
cd NanotechSoft
cp .env.example .env
docker compose up -d mysql pacs-postgres
```

Esse compose publica o MySQL do portal na porta `3307` e o PostgreSQL do
RaioxPacs na porta `5433`, para nao conflitar com bancos locais padrao.

Dentro da rede Docker, o portal acessa:

- MySQL do portal: `mysql:3306`.
- PostgreSQL do PACS: `pacs-postgres:5432`.

De fora do Docker, use:

- MySQL do portal: `127.0.0.1:3307`.
- PostgreSQL do PACS: `127.0.0.1:5433`.

Com o banco do compose, mantenha `NS_DB_PORT=3307`, `RAIOXPACS_PGHOST=pacs-postgres`
e `RAIOXPACS_PGPORT=5432` no `.env`.

## Arquivos de ambiente

O app carrega as variaveis nesta ordem:

- `NANOTECH_ENV_FILE`, quando essa variavel aponta para um arquivo.
- `.env`, se existir.
- `.env_local`, se nao existir `.env`.

No Git ficam as configuracoes versionadas: `.env.example`/`docker-compose.yml`
para uso local e `render.yaml` para o Render. Use `.env_local` apenas para
valores reais da sua maquina; esse arquivo fica ignorado pelo Git para evitar
vazamento de senha.

Para rodar local explicitamente:

```bash
NANOTECH_ENV_FILE=.env_local python app.py
```

No Render, use o `render.yaml`; ele preserva as variaveis `NS_DB_*` configuradas
no painel para o servidor MySQL unico. Para o PACS, configure tambem as variaveis
`RAIOXPACS_*` para apontar ao PostgreSQL publicado do servidor local ou a um
PostgreSQL externo.

## Deploy no Render

A branch `main` contem tambem a configuracao externa. O `render.yaml` define o
Web Service:

- `nanotechsoft`: web service Docker do portal.

No Render, importe o Blueprint a partir da branch `main`. Criar apenas um
Web Service manual exige a configuracao equivalente das variaveis no painel.

No Render, configure `RIOB_BASE_URL` com a URL HTTPS publica da origem RioB.
O Portal atua como proxy reverso: o navegador permanece na URL do Render e o IP
da origem nao aparece nos links da interface. Se essa variavel estiver ausente,
o Render retorna erro de configuracao e nao inicia outro RioB no mesmo container.
O `render.yaml` fixa `RIOB_PROXY_ONLY=1`; o fallback por subprocesso permanece
disponivel apenas em ambientes locais com `RIOB_PROXY_ONLY=0`.

Valide a origem configurada em `/healthz/riob`. Esse diagnostico consulta
`/api/status` no servidor RioB sem expor a URL completa da origem.

O Render nao oferece MySQL gerenciado nativo como oferece Postgres; este projeto
acessa o servidor MySQL unico informado em `NS_DB_*`. Para producao, faca
backups periodicos com `mysqldump`.

### Validacao obrigatoria do RioB no Render

O auto-deploy do Render publica codigo, mas nao copia o banco MySQL local. O
RioB publicado usa o schema `riobranco` do servidor informado em `NS_DB_*`;
portanto, uma tela vazia pode significar que o servico esta saudavel, mas
conectado a um schema vazio ou diferente.

O portal e o RioB devem usar um unico servidor MySQL, configurado no Web Service
pelas variaveis `NS_DB_HOST`, `NS_DB_PORT`, `NS_DB_USER` e `NS_DB_PASSWORD`.
Nesse servidor, `NS_DB_NAME` seleciona o schema do portal (`notechsoft`) e
`RIOB_DB_NAME` seleciona o schema operacional do RioB (`riobranco`). O
`render.yaml` nao deve sobrescrever essas variaveis com outro MySQL.

Antes de considerar uma alteracao concluida:

1. confirme que o commit esperado esta em `origin/main`;
2. confirme no Render que esse mesmo commit terminou o deploy;
3. teste `/healthz` e tambem uma rota de dados do recurso alterado pela URL
   publica;
4. confirme, somente com consultas de leitura, que o schema persistente do
   Render contem os registros esperados;
5. trate backup, restore ou sincronizacao de dados como operacao separada,
   explicitamente autorizada e nunca como efeito colateral do deploy.

Um `200` em `/healthz` comprova apenas que o portal esta respondendo; ele nao
valida o subprocesso RioB nem a presenca dos dados de negocio.

O RaioxPacs usa PostgreSQL separado do MySQL do portal. No deploy Docker local,
o servico `pacs-postgres` e publicado somente no loopback do host em
`127.0.0.1:RAIOXPACS_POSTGRES_PORT`, por padrao `127.0.0.1:5433`, e o container
`app` recebe `RAIOXPACS_PGHOST=pacs-postgres`,
`RAIOXPACS_PGPORT=5432`, `RAIOXPACS_PGUSER`, `RAIOXPACS_PGPASSWORD` e
`RAIOXPACS_PGDATABASE`.

O PostgreSQL nao e publicado diretamente. O servico
`pacs-postgres-gateway` publica a porta externa e aceita somente os blocos de
saida do Render declarados em `deploy/postgres-gateway/haproxy.cfg`; qualquer
outra origem e recusada antes de chegar ao banco. O PostgreSQL usa TLS e a URL
externa deve manter `sslmode=require`. Se os IPs de saida do Render mudarem,
atualize a allowlist antes do deploy. Depois configure no web service:

- `RAIOXPACS_PGHOST`: IP/DNS publico que chega ao servidor Docker local.
- `RAIOXPACS_PGPORT`: porta encaminhada, por padrao `5433`.
- `RAIOXPACS_PGUSER`: usuario do Postgres, por padrao `postgres`.
- `RAIOXPACS_PGPASSWORD`: senha configurada no `.env`.
- `RAIOXPACS_PGDATABASE`: banco do PACS, por padrao `raioxpacs`.
- `RAIOXPACS_PGSSLMODE`: `require` para qualquer conexao externa.

Tambem e possivel preencher `RAIOXPACS_DATABASE_URL` no Render; se ela existir,
ela tem prioridade sobre as variaveis `RAIOXPACS_PG*`.

Configure o servidor MySQL unico no Web Service do Render com estas variaveis:

- `NS_DB_HOST`
- `NS_DB_PORT`
- `NS_DB_USER`
- `NS_DB_PASSWORD`
- `NS_DB_NAME`

Nao use SQLite para o portal principal sem uma refatoracao: o app usa
`mysql.connector`, tipos/DDL de MySQL e tabelas com JSON/AUTO_INCREMENT.

### Backup JSON pelo navegador

A tela `Config` possui um painel `Backup do portal` para administradores. Ele
exporta todas as tabelas do banco principal para um arquivo JSON e permite
importar esse JSON de volta para o MySQL atual.

Esse recurso serve como metodologia simples para ambiente inicial/free: baixe o
backup antes de redeploys ou trocas de banco, guarde o arquivo em um local
externo como Google Drive e importe quando precisar reconstruir os dados.
Ele nao substitui o MySQL em tempo de execucao; a aplicacao ainda precisa estar
conectada a um banco MySQL/MariaDB para abrir e para restaurar o arquivo.

## Scripts operacionais

Os quatro comandos operacionais canônicos ficam na raiz:

```bash
./up.sh
./down.sh
./update.sh
./git-safe-push.sh -m "mensagem do commit"
```

- `./up.sh` reconstrói e sobe portal e RioB para teste, preservando os bancos e volumes.
- `./down.sh` para portal e RioB, sem parar, restaurar ou sincronizar bancos.
- `./update.sh` atualiza o código e recria somente as aplicações em produção, sem operar bancos.
- `./git-safe-push.sh` bloqueia arquivos sensíveis/runtime, valida portal e RioB, cria o commit e envia a branch atual para `origin`.

Não existem scripts operacionais próprios dentro dos apps. Consulte
`docs/AI_RESEARCH_MANUAL.md` para os contratos completos e pressupostos
permanentes do projeto.

Os scripts detectam `docker compose`, `docker-compose` ou `podman compose`. Se o Docker CLI nao estiver disponivel no terminal atual, execute os scripts fora de sandboxes que nao exponham Docker, como alguns ambientes Flatpak, ou instale o plugin Compose.

Em um ambiente sem Docker CLI, o `./git-safe` pula Compose/build/health automaticamente e ainda roda as validacoes de Python, manifests e clientes. Use `--skip-compose` quando quiser deixar esse pulo explicito. Use `--skip-whitespace` somente quando precisar ignorar `git diff --check`; por padrao, vendors minificados e binarios ja sao excluidos dessa checagem. Se faltarem dependencias Python locais, a validacao que importa `app.py` vira aviso; instale `requirements.txt` para checar tambem rotas e temas fora do container.

## Apps dinamicos

Os apps ficam dentro de `apps/`. Cada subpasta pode ter um `app.json`; tambem existe a tabela `installed_apps` para cadastro via banco.

O arquivo `clientes-modulos.json` define os clientes e quais modulos cada um possui. No deploy, configure `CLIENTE_DEPLOY_ID` com o ID do cliente, por exemplo `rio-branco`. Cada ambiente continua usando seu proprio banco via `NS_DB_NAME`/credenciais, sem misturar dados entre clientes.

Se `CLIENTE_DEPLOY_ID` nao estiver configurado, o portal usa `apps_liberados.txt` como fallback local/legado.

Administradores tambem podem editar esse arquivo pela tela `Config`, ou pelas rotas:

- `GET /api/clientes-modulos`
- `GET /api/clientes-modulos/ativo`
- `POST /api/clientes-modulos/clientes`
- `PUT /api/clientes-modulos/clientes/<id>`
- `DELETE /api/clientes-modulos/clientes/<id>`

## Codigo dos apps

Esta plataforma nao deve depender de codigo em outros diretorios do servidor. O codigo de cada app deve ficar dentro da propria pasta do projeto:

- apps Flask/servicos: `apps/<app>/source`
- apps estaticos: `apps/<app>/source`
- Financeiro integrado: `apps/financeiro`
- RioB e modulos locais: `apps/riob/source`, `apps/riob-cameras/source`, `apps/riob-email/source`, `apps/riob-esxi/source` e `apps/riob-xml/source`

Arquivos operacionais gerados em uso, como bancos SQLite, anexos, XMLs enviados, uploads e streams `.m3u8`, ficam ignorados pelo Git.
Schemas SQL necessarios para boot dos apps embarcados, como
`apps/automacao/source/schema.sql`, fazem parte do codigo e devem permanecer
versionados.

Os manifests podem separar atalhos em `dashboards`, `cadastros`, `workflow`, `compras`, `financeiro`, `relatorios` e `import_export`; configuracoes especificas entram em `config_groups`.

## Permissoes por usuario

Usuarios com `perfil='admin'` acessam todos os apps e funcoes.

Usuarios comuns dependem da tabela `usuario_app_permissoes`:

- `app_key`: app liberado, como `financeiro` ou `automacao`
- `recurso`: funcao do app, como `dashboard`, `contas`, `categorias`, `compras`, `pagar`, `receber`, `config`; use `*` para liberar o app inteiro
- `permitido`: `1` libera o recurso

O menu principal e as abas internas do financeiro ocultam recursos sem permissao.

## Financeiro

O app financeiro fica em `apps/financeiro` e roda integrado ao shell do NanotechSoft. Os dados foram migrados do backup JSON inicial para MySQL nas tabelas `financeiro_registros` e `financeiro_config`.

O tema padrao do portal continua sendo `Rio Branco`. O tema original do financeiro fica disponivel como `Fin Blue`, e o tema do RaioxPacs fica disponivel como `PACS Red`; nenhum deles e aplicado automaticamente ao abrir um app.
