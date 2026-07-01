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

## MySQL com Docker

```bash
cd NanotechSoft
cp .env.example .env
docker compose up -d mysql
```

Esse compose publica o banco na porta `3307` por padrao para nao conflitar com outros MySQL locais.

Com o banco do compose, mantenha `NS_DB_PORT=3307` no `.env`.

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

No Render, use o `render.yaml`; ele cria o MySQL privado e injeta as variaveis
necessarias no web service.

## Deploy no Render

A branch `main` contem tambem a configuracao externa. O `render.yaml` define
dois servicos:

- `nanotechsoft`: web service Docker do portal.
- `nanotechsoft-mysql`: MySQL 8 como private service com disco persistente em
  `/var/lib/mysql`.

No Render, importe o Blueprint a partir da branch `main`. Criar apenas um
Web Service manual nao aplica as variaveis do `render.yaml`; nesse caso o app
cai no padrao local `127.0.0.1:3307` e nao encontra o MySQL.

O Render nao oferece MySQL gerenciado nativo como oferece Postgres; este projeto
usa MySQL em private service com Render Disk. Para producao, faca backups
periodicos com `mysqldump`, porque snapshot de disco nao substitui backup logico
de banco.

Se preferir usar um MySQL externo, remova ou ignore o servico
`nanotechsoft-mysql` no Render e configure estas variaveis no web service:

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

Os atalhos da raiz podem ser usados com ou sem `.sh`:

```bash
./up
./down
./git-safe -m "mensagem do commit"
```

- `./up` sobe ou recria `mysql` e `app`, valida os manifests dos apps e espera `/login` responder.
- `./down` para somente o container `app`, preservando o banco e o volume MySQL.
- `./git-safe` bloqueia arquivos sensiveis/runtime, valida Python, valida `source_dir` dos apps, executa `docker compose config`, opcionalmente builda/testa o container e envia a branch atual para `origin`.

Os scripts detectam `docker compose`, `docker-compose` ou `podman compose`. Se o Docker CLI nao estiver disponivel no terminal atual, execute os scripts fora de sandboxes que nao exponham Docker, como alguns ambientes Flatpak, ou instale o plugin Compose.

Em um ambiente sem Docker CLI, `./git-safe --skip-compose -m "mensagem"` permite commitar/enviar depois das validacoes de Python e manifests, pulando build e healthcheck do container explicitamente.

## Apps dinamicos

Os apps ficam dentro de `apps/`. Cada subpasta pode ter um `app.json`; tambem existe a tabela `installed_apps` para cadastro via banco.

O arquivo `apps_liberados.txt` define quais apps aparecem no portal e devem ser carregados no deploy do cliente. Nesta etapa, os apps liberados sao `automacao` e `financeiro`.

## Codigo dos apps

Esta plataforma nao deve depender de codigo em outros diretorios do servidor. O codigo de cada app deve ficar dentro da propria pasta do projeto:

- apps Flask/servicos: `apps/<app>/source`
- apps estaticos: `apps/<app>/source`
- Financeiro integrado: `apps/financeiro`
- RioB e modulos locais: `apps/riob/source`, `apps/riob-cameras/source`, `apps/riob-email/source`, `apps/riob-esxi/source` e `apps/riob-xml/source`

Arquivos operacionais gerados em uso, como bancos SQLite, anexos, XMLs enviados, uploads e streams `.m3u8`, ficam ignorados pelo Git.

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

O tema padrao do portal continua sendo `Rio Branco`. O tema original do financeiro fica disponivel como `Fin Blue` no seletor de temas, sem ser aplicado automaticamente ao abrir o app.
