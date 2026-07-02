# Laboratorio Santa Terezinha

Projeto para operar a unidade da Laboratorio Santa Terezinha com RIS e PACS proprio, sem depender mais do CharruaSoft.

## O que este MVP entrega

- cockpit unico com dashboard, kanban, cadastros, RIS e PACS, worklist e storage;
- menu `Config` em submenus para apontar PACS e MWL externos por IP, porta e AE Title;
- tela de login por departamento, com acesso admin liberado na propria entrada do sistema;
- chat interno entre departamentos e painel de chamadas;
- painel de chamadas no estilo Cardio Clin, com video e anuncio por voz;
- schema proprio `raiox` dentro do PostgreSQL do PACS;
- PACS DICOM proprio com `C-ECHO`, `C-STORE`, `C-FIND`, `C-GET` e `C-MOVE` configuravel;
- catalogo local de `public.worklist`, `public.study`, `public.series`, `public.reports` e `public.objects`, agora mantido pelo proprio projeto;
- publicacao de exames da clinica na worklist DICOM local;
- consulta rapida de procedimentos cadastrados na aba `Exames`, com busca por nome para editar o cadastro;
- configuracao de convênios com suporte a criar e remover registros pela tela `Config`;
- financeiro com baixa de pagamento por dinheiro, pix, cartao ou cheque;
- menu `Relatorio` com filtros por dia, mes, convenio e paciente, PDF em nova aba e resumo financeiro no dashboard;
- relatorios com filtros por periodo, convenio e paciente, com resumo financeiro e PDF rapido;
- monitoramento do espaco do disco das imagens.

## Estrategia de integracao

- o projeto sobe um PACS proprio no PostgreSQL configurado;
- a clinica usa tabelas proprias em `raiox.*` para paciente, procedimento, exame, faturamento, operadores, chat, senhas do painel e log de sincronizacao;
- a worklist DICOM nasce na aplicacao e e servida pelo `RAIOXMWL`;
- as imagens recebidas por `C-STORE` sao persistidas no storage local e catalogadas em `public.study`, `public.series` e `public.objects`;
- a consulta e recuperacao seguem o fluxo padrao de `Study Root Query/Retrieve`.

Quando o cockpit web for publicado separado do PACS:

- o banco pode ficar local por padrao, usando `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE` ou `DATABASE_URL` quando voce quiser apontar para fora;
- o menu `Config` permite alternar PACS e MWL entre `local` e `externo`;
- os status efetivos de banco, PACS e worklist ficam concentrados dentro da propria aba `Config`.

## Como rodar

```bash
cd /srv/raioxPacs
cp .env.example .env
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
flask --app app run --host 0.0.0.0 --port 5020
```

Se o seu WSL ainda estiver sem `python3-venv`, rode com o Python do usuario:

```bash
cd /srv/raioxPacs
python3 -m pip install --user -r requirements.txt
python3 -m flask --app app run --host 0.0.0.0 --port 5020
```

## Stack Docker

O projeto tambem pode subir inteiro por Docker, incluindo:

- app web Flask/Gunicorn;
- PostgreSQL com o banco `raioxpacs`;
- servidor DICOM Modality Worklist (`RAIOXMWL`) em container proprio;
- servidor PACS DICOM (`RAIOXPACS`) com Store/Query/Retrieve em container proprio.

Arquivos principais:

- `Dockerfile`
- `docker-compose.yml`
- `docker/init/00-raioxpacs-stack.sql`
- `scripts/deploy/up.sh`
- `scripts/deploy/bootstrap-clone.sh`
- `pendrive-bootstrap.sh`
- `.env.docker.example`

### Deploy automatico

Primeira execucao, quando o banco ainda precisa ser criado/preparado:

```bash
cd /srv/raioxPacs
cp .env.docker.example .env.docker
./scripts/deploy/first_boot.sh
```

Atualizacao de producao sem aplicar bootstrap/mudancas no banco:

```bash
cd /srv/raioxPacs
./scripts/deploy/update.sh
```

Em um servidor Ubuntu limpo, o projeto tambem pode fazer o bootstrap do host:

```bash
cd /srv/raioxPacs
./scripts/deploy/first_boot.sh
```

Esse bootstrap prioriza subir a stack local com o `.env.docker` do proprio projeto e nao bloqueia por uma
checagem externa de rede. Se quiser diagnosticar conectividade antes, rode `./scripts/deploy/check-network.sh`
separadamente.

Se ainda nao existir um clone local, use o bootstrap completo que cria a pasta, clona o repositorio, configura as credenciais do Git quando informado e dispara o primeiro deploy:

```bash
GIT_REPO_URL=https://github.com/seu-org/raioxPacs.git \
GIT_TARGET_DIR=/srv/raioxPacs \
GIT_USER_NAME="Seu Nome" \
GIT_USER_EMAIL="voce@exemplo.com" \
GIT_CREDENTIAL_USERNAME="seu-usuario" \
GIT_CREDENTIAL_TOKEN="seu-token" \
./scripts/deploy/bootstrap-clone.sh
```

Para levar em um pendrive e executar em outra maquina sem passar parametros na hora, use o arquivo raiz `pendrive-bootstrap.sh`.

Coloque junto dele a sua chave privada SSH ja usada nesta maquina, com o nome `id_ed25519`, e deixe tambem um `known_hosts` local ao lado. A chave publica correspondente deve estar cadastrada no GitHub/GitLab:

```bash
chmod +x pendrive-bootstrap.sh
./pendrive-bootstrap.sh
```

Se a chave tiver passphrase, o `ssh` pode pedir a senha durante o clone. O arquivo `known_hosts` sera criado ou atualizado no proprio pendrive. Para uso totalmente automatico, use uma chave sem passphrase ou carregada no `ssh-agent`.

Esse fluxo:

- instala Docker Engine e Docker Compose Plugin se ainda nao existirem;
- cria `.env.docker` automaticamente a partir do exemplo;
- no primeiro boot, nao bloqueia por checagem externa de rede;
- prepara `runtime/imagebox` e `runtime/backups`;
- sobe PostgreSQL, app web, MWL DICOM e PACS DICOM;
- reconstrui os containers quando houver alteracao de codigo.

O `update.sh` faz `git pull --ff-only`, reconstrui apenas `app`, `worklist` e `dicom` com `AUTO_BOOTSTRAP_SCHEMA=0`, e nao recria o servico `db`. Se quiser atualizar a imagem sem puxar Git, rode `RAIOX_SKIP_GIT_PULL=1 ./scripts/deploy/update.sh`.

Para publicar codigo no Git sem enviar arquivos locais desnecessarios ou sensiveis:

```bash
cd /srv/raioxPacs
./scripts/deploy/publish-git.sh -m "mensagem do commit"
```

Antes de commit/push, esse script bloqueia `.env`, `render.env`, runtime, dumps, backups e logs; tambem valida os scripts de deploy e compila os modulos Python.

Quando o remote Git usa SSH, o script tenta usar automaticamente uma chave privada local em uma destas rotas:

- `~/.ssh/id_ed25519`
- `~/.ssh/id_ed25519_github`
- `~/.ssh/id_rsa`
- `~/.ssh/id_rsa_github`

Se quiser forcar outra chave, rode assim:

```bash
GIT_SSH_KEY_FILE=/caminho/da/sua_chave \
./scripts/deploy/publish-git.sh -m "mensagem do commit"
```

Para criar acesso remoto de manutencao por SSH no servidor:

```bash
cd /srv/raioxPacs
./scripts/deploy/setup-remote-ssh.sh --user raioxadmin --public-key "COLE_A_CHAVE_PUBLICA_AQUI"
```

Depois teste de fora:

```bash
ssh -p 22 raioxadmin@IP_OU_DNS_DA_PRODUCAO
```

Depois disso, a stack sobe com:

- app: `http://localhost:5020`
- postgres: `localhost:5432`
- PACS DICOM: `localhost:11112`
- worklist DICOM: `localhost:11115`
- AE Titles:
  `RAIOXPACS` para Store/Query/Retrieve
  `RAIOXMWL` para Modality Worklist

O `Dockerfile` instala `ffmpeg`, e o `docker-compose.yml` persiste:

- `runtime/imagebox`

### Operacao do stack

```bash
cd /srv/raioxPacs
./scripts/deploy/status.sh
./scripts/deploy/logs.sh
./scripts/deploy/logs.sh app
./scripts/deploy/down.sh
```

### Migracao completa para outra maquina

Para gerar um pacote unico com arquivos do sistema, `.env`, dados persistidos de `runtime/` e dump completo do PostgreSQL:

```bash
cd /srv/raioxPacs
./migrar.sh
```

O arquivo final fica em `runtime/backups/migration/raioxpacs-migracao-YYYYMMDD-HHMMSS.tar.gz`.

Na maquina de destino, copie esse arquivo para a pasta do projeto e rode:

```bash
cd /srv/raioxPacs
./deploybackp.sh /caminho/raioxpacs-migracao-YYYYMMDD-HHMMSS.tar.gz
```

O restore cria antes um snapshot preventivo do destino em `runtime/backups/restore/`, restaura os arquivos,
recria o banco PostgreSQL a partir do dump, sobe a stack completa e deixa o sistema pronto para uso.

### Troubleshooting de rede

Se o deploy parar com erro de `registry-1.docker.io`, o problema costuma ser rede/proxy do host e nao da stack. O script [check-network.sh](/srv/raioxPacs/scripts/deploy/check-network.sh) agora valida isso antes do `compose up`.

Diagnostico rapido:

```bash
cd /srv/raioxPacs
./scripts/deploy/check-network.sh
```

Se as imagens ja estiverem em cache local e voce quiser forcar a subida sem essa checagem:

```bash
cd /srv/raioxPacs
RAIOX_SKIP_NETWORK_CHECK=1 ./scripts/deploy/up.sh
```

## Git

O projeto ja esta inicializado em Git, na branch `main`, e o `.gitignore` ja protege os arquivos locais mais sensiveis, como `.env`, `.env.docker`, `.venv/`, `runtime/` e `pgdata/`.

Para publicar em um repositorio novo no GitHub ou GitLab:

```bash
cd /srv/raioxPacs
git remote add origin <URL_DO_REPOSITORIO>
git push -u origin main
```

Se voce fizer novas alteracoes antes do envio:

```bash
cd /srv/raioxPacs
git status
git add .
git commit -m "Sua mensagem"
git push
```

Se quiser confirmar o remoto configurado:

```bash
cd /srv/raioxPacs
git remote -v
```

## Deploy opcional no Render com PostgreSQL externo

O projeto tambem pode fazer deploy `web-only` no Render, mas isso e opcional:

- blueprint em `render.yaml`;
- exemplo de variaveis em `.env.render.example`;
- suporte a `DATABASE_URL`, `PGSSLMODE`, `PORT` e `RUNTIME_ROOT` quando voce quiser usar banco externo;
- links de compartilhamento usando a URL publica configurada no menu `Config`.

Fluxo recomendado:

```bash
cd /srv/raioxPacs
cat .env.render.example
```

No Render:

1. conecte o reposit??rio e escolha `Blueprint` usando `render.yaml`;
2. preencha `DATABASE_URL` com o PostgreSQL externo de sua escolha apenas se nao quiser usar o banco local;
3. ajuste `PACS_WEB_URL` para a URL final do servico;
4. deixe `RUNTIME_ROOT=/opt/render/project/src/runtime`;
5. apos o primeiro boot, abra o menu `Config` e informe PACS/MWL externos se eles nao estiverem no mesmo host da interface.

Observacao importante:

- o Render atende muito bem a interface HTTP do cockpit;
- PACS DICOM e MWL costumam ficar fora desse servico web, apontados como externos pelo menu `Config`, porque a publicacao web e diferente da exposicao de portas DICOM.

## GitHub + Render automatico

O repositorio agora pode seguir este fluxo:

- `develop` -> deploy automatico de homologacao;
- `main` -> deploy automatico de producao;
- banco PostgreSQL externo via `DATABASE_URL`;
- Render acionado por deploy hooks disparados no GitHub Actions.

Arquivos adicionados:

- `.github/workflows/deploy-homolog.yml`
- `.github/workflows/deploy-production.yml`

Secrets esperados no GitHub:

- `RENDER_DEPLOY_HOOK_HOMOLOG`
- `RENDER_DEPLOY_HOOK_PRODUCTION`

Configuracao sugerida no Render:

1. criar um servico `web` para homologacao e outro para producao;
2. apontar ambos para o mesmo repositorio;
3. usar o mesmo blueprint/base da aplicacao, mas com `autoDeploy` desligado;
4. configurar `DATABASE_URL`, `APP_SECRET_KEY`, `RUNTIME_ROOT` e `PACS_WEB_URL` em cada ambiente;
5. copiar o deploy hook de cada servico para o secret correspondente no GitHub.

Antes de publicar uma nova versao, gere os backups pela tela `Storage`:

- backup do banco;
- backup das imagens e anexos.

## Bootstrap do banco

Se `AUTO_BOOTSTRAP_SCHEMA=1`, o schema `raiox` e as tabelas da clinica sao criados automaticamente na subida da aplicacao.

No primeiro deploy, o bootstrap tambem:

- importa automaticamente os procedimentos do `scripts/import_tabela_exames.sql` no bootstrap;
- cria o convênio `PARTICULAR` como base da tabela de preços;
- usa os valores salvos em `PARTICULAR` no menu `Config`, com fallback para o `default_price` do procedimento quando ainda nao houver valor configurado;
- deixa a manutencao de outros convênios para o menu `Config`;
- exibe os status do sistema dentro de `Config`, sem repetir esses cards na barra lateral.

Tambem e possivel inicializar manualmente:

```bash
cd /srv/raioxPacs
. .venv/bin/activate
python scripts/bootstrap_db.py
```

## Banco esperado

- PACS: `raioxpacs`
- Usuario: `postgres`
- Senha: `rocklee23`
- Worklist PACS: `public.worklist`
- Estudos PACS: `public.study`
- Series PACS: `public.series`
- Objetos PACS: `public.objects`

## Proximo passo recomendado

Depois de validar o fluxo, o natural e conectar:

- regras reais de faturamento por convenio;
- importacao de agenda externa/HL7;
- politica automatica de limpeza/arquivamento por storage tiers;
- dashboards por medico, modalidade e equipamento;
- integracao futura de telefonia, se a clinica realmente precisar;
- telemetria operacional e alertas do painel.
