# Operacao e Deploy da Laboratorio Santa Terezinha

## 1. Principios operacionais

A Laboratorio Santa Terezinha foi pensada para ser simples de subir, mas ela depende de tres verdades:

1. o banco precisa estar acessivel;
2. a porta HTTP precisa seguir `PORT` ou `APP_PORT`;
3. o runtime local precisa ter permissoes para gravar imagens, streams e backups.

## 2. Modos de execucao

## 2.1 Execucao local com Python

Fluxo basico:

```bash
cd /srv/raioxPacs
cp .env.example .env
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
flask --app app run --host 0.0.0.0 --port 5020
```

Quando usar:

- desenvolvimento local;
- homologacao rapida sem Docker;
- depuracao do Flask e das rotas.

## 2.2 Stack Docker

Arquivos principais:

- `Dockerfile`
- `docker-compose.yml`
- `docker/init/00-raioxpacs-stack.sql`
- `docker/entrypoint.sh`
- `scripts/deploy/*.sh`

Se voce ainda nao tiver um clone local, o bootstrap `scripts/deploy/bootstrap-clone.sh` cria a pasta, faz o clone, configura credenciais do Git quando informadas e chama o primeiro deploy automaticamente.

Para um uso ainda mais portatil, existe um arquivo raiz `pendrive-bootstrap.sh` com repo, branch e identidade do Git ja preenchidos. Basta copiar para o pendrive, colocar a chave privada SSH ao lado dele com o nome `id_ed25519`, manter o `known_hosts` local no mesmo diretorio, dar permissao de execucao e rodar.

O clone usa a URL SSH do GitHub e assume que a chave publica correspondente ja esta cadastrada na conta. O arquivo `known_hosts` fica local no pendrive e e usado para verificar o host. Se a chave tiver passphrase, o `ssh` pode solicitar a senha durante o clone; para automacao total, prefira uma chave sem passphrase ou carregada no `ssh-agent`.

Fluxo recomendado:

Primeira execucao, com criacao/preparo do banco:

```bash
cd /srv/raioxPacs
cp .env.docker.example .env.docker
./scripts/deploy/first_boot.sh
```

Atualizacao de producao sem bootstrap de banco:

```bash
cd /srv/raioxPacs
./scripts/deploy/update.sh
```

A stack pode subir:

- app web;
- PostgreSQL;
- MWL DICOM;
- PACS DICOM.

## 2.3 Deploy web-only opcional no Render

Quando o ambiente publica apenas HTTP:

- o cockpit sobe como servico web;
- PACS e MWL podem ficar externos;
- `DATABASE_URL` e opcional; para uso local, prefira `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE`;
- `RUNTIME_ROOT` precisa apontar para um disco persistente quando houver.

O blueprint atual esta em `render.yaml`.

## 3. Variaveis de ambiente mais importantes

| Variavel | Uso |
| --- | --- |
| `PORT` | Porta HTTP prioritaria em PaaS |
| `APP_PORT` | Fallback da porta web em ambientes locais |
| `APP_HOST` | Host bind do Gunicorn/Flask |
| `DATABASE_URL` | Conexao completa com PostgreSQL externo |
| `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` | Configuracao preferida para banco local |
| `PGSSLMODE` | Controle de SSL do PostgreSQL |
| `RUNTIME_ROOT` | Raiz operacional para imagebox e backups |
| `PACS_IMAGEBOX_PATH` | Pasta das imagens DICOM persistidas |
| `AUTO_BOOTSTRAP_SCHEMA` | Liga/desliga bootstrap automatico do schema |
| `PACS_AET` | AE Title do PACS local |
| `DICOM_PORT` | Porta do PACS DICOM |
| `WORKLIST_AE_TITLE` | AE Title da MWL local |
| `WORKLIST_PORT` | Porta da MWL local |
| `PACS_WEB_URL` | URL publica base do cockpit |
| `APP_SECRET_KEY` | Chave de sessao Flask |

## 4. Portas padrao

| Servico | Porta padrao |
| --- | --- |
| Cockpit web | `5020` ou `PORT` |
| PostgreSQL | `5432` |
| PACS DICOM | `11112` |
| Worklist DICOM | `11115` |

## 5. Bootstrap de banco

O startup normal chama:

1. `scripts/wait_for_db.py`
2. `scripts/bootstrap_db.py`, apenas quando `AUTO_BOOTSTRAP_SCHEMA=1`
3. app web, MWL ou PACS

Efeitos do bootstrap:

- cria schema `raiox`;
- cria tabelas clinicas;
- garante tabelas `public.*` necessarias ao PACS;
- reaplica automaticamente `scripts/import_tabela_exames.sql` quando o hash do arquivo muda;
- semeia configuracoes padrao;
- cria operadores padrao se ainda nao existirem.

No primeiro deploy, o fluxo esperado e:

- importar os exames e procedimentos de `scripts/import_tabela_exames.sql`;
- criar o convênio `PARTICULAR` como base da tabela de valores;
- usar os valores salvos em `PARTICULAR` no menu `Config`, com fallback para o `default_price` do procedimento quando ainda nao houver valor configurado;
- deixar a criacao e remocao dos demais convênios para o menu `Config`.

### Atualizacao da tabela de exames por planilha

A planilha operacional fica em `scripts/examesatualizado.xlsx` e deve conter as abas `particular` e `convenios`, com as colunas:

- `NOME DO EXAME`
- `1incidencia`
- `2incidencia`
- `3incidencia`

Para gerar o SQL usado no primeiro deploy e tambem o SQL avulso para uma producao existente:

```bash
python scripts/generate_import_tabela_exames_sql.py --input scripts/examesatualizado.xlsx
```

Esse comando atualiza:

- `scripts/import_tabela_exames.sql`, executado automaticamente no bootstrap/primeiro deploy;
- `scripts/update_tabela_exames_producao.sql`, usado para atualizar uma producao ja existente.

Para aplicar em producao com Docker:

```bash
cd /srv/raioxPacs
./scripts/deploy/apply-exam-table.sh
```

O script gera backup logico do catalogo antes de aplicar. Procedimentos que nao estao na planilha ficam inativos, preservando historico de exames antigos.

## 6. Rotina operacional recomendada

### Antes de abrir a operacao

- validar banco e porta;
- conferir `Storage`;
- revisar `Config` para PACS/MWL efetivos;
- testar `/api/ping` e `/api/health`;
- confirmar que backups recentes existem antes de mudancas maiores.

### Antes de deploy ou update

- gerar backup do banco;
- gerar backup das imagens;
- conferir se `RUNTIME_ROOT` e `PACS_IMAGEBOX_PATH` sao persistentes;
- revisar `.env`, `.env.docker` ou variaveis do host.
- para atualizar sem mexer no banco, usar `./scripts/deploy/update.sh`, que sobe `app`, `worklist` e `dicom` com `AUTO_BOOTSTRAP_SCHEMA=0` e `--no-deps`.

### Depois do deploy

- abrir o cockpit;
- abrir `/docs/index.html`;
- verificar `Dashboard`, `Config` e `Storage`;

### Publicacao de codigo no Git

Para publicar alteracoes locais com a protecao contra envio de `.env`, runtime, backups e dumps:

```bash
cd /srv/raioxPacs
./scripts/deploy/publish-git.sh -m "mensagem do commit"
```

Se o remote estiver em SSH, o script tenta usar automaticamente uma chave privada local em:

- `~/.ssh/id_ed25519`
- `~/.ssh/id_ed25519_github`
- `~/.ssh/id_rsa`
- `~/.ssh/id_rsa_github`

Para forcar uma chave especifica:

```bash
GIT_SSH_KEY_FILE=/caminho/da/sua_chave \
./scripts/deploy/publish-git.sh -m "mensagem do commit"
```

## 6.1 Acesso remoto de manutencao

Para manutencao pela rede externa, use SSH com chave publica. Nao coloque chave privada, senha real ou arquivo `.env` no Git.

No computador que fara a manutencao, gere uma chave se ainda nao existir:

```bash
ssh-keygen -t ed25519 -C "manutencao-raiox"
cat ~/.ssh/id_ed25519.pub
```

No servidor de producao, com acesso local ou console da hospedagem, rode:

```bash
cd /srv/raioxPacs
./scripts/deploy/setup-remote-ssh.sh \
  --user raioxadmin \
  --public-key "COLE_A_CHAVE_PUBLICA_AQUI"
```

Se souber o IP fixo de onde voce fara manutencao, restrinja a origem:

```bash
./scripts/deploy/setup-remote-ssh.sh \
  --user raioxadmin \
  --allow-cidr 200.10.20.30/32 \
  --public-key "COLE_A_CHAVE_PUBLICA_AQUI"
```

Teste de fora antes de encerrar o acesso local:

```bash
ssh -p 22 raioxadmin@IP_OU_DNS_DA_PRODUCAO
cd /srv/raioxPacs
./scripts/deploy/status.sh
```

Se o servidor estiver atras de roteador/NAT, encaminhe a porta TCP `22` do roteador para o IP interno do servidor. Se nao houver IP publico ou encaminhamento de porta, use uma VPN/tunel de acesso, como Tailscale, WireGuard ou um tunel reverso SSH, e mantenha o SSH aberto apenas pela rede privada da VPN.

## 7. Fluxos recentes

- a manutencao de exames usa uma busca rapida para localizar procedimentos cadastrados pelo nome e abrir o cadastro para edicao;
- a area de convênios ganhou o botao `Novo convênio` na tela `Config`, com opcoes para criar, remover e restaurar convênios sem editar o banco manualmente;
- a area financeira aceita baixa com `dinheiro`, `pix`, `cartao` e `cheque`, tanto na lista principal quanto no popup do exame;
- o popup do fluxo de trabalho inclui atalhos para `Exames`, `Valores`, `Worklist`, `Painel`, `Laudos e Viewer` e `Financeiro`.
- validar um fluxo curto: cadastro, worklist, workspace e painel.

## 7. Backup

O sistema oferece duas operacoes principais na tela `Storage`:

- backup de banco;
- backup de imagens/anexos.

Detalhes importantes:

- para banco, a estrategia preferida e `pg_dump`;
- se `pg_dump` nao estiver disponivel, o projeto usa um fallback logico;
- para imagens, o foco e empacotar o runtime clinico necessario para recuperacao operacional.

## 8. Troubleshooting

## 8.1 Timeout de deploy por porta

Sintoma comum:

- a plataforma nao detecta porta aberta;
- aparece erro de `Port scan timeout` ou similar.

Checklist:

1. confirmar se o processo web esta bindando em `PORT`;
2. conferir `docker/entrypoint.sh` ou `render.yaml` se estiver no modo web-only;
3. revisar logs para ver se o banco esta travando a subida antes do Gunicorn;
4. garantir que `APP_HOST` esteja em `0.0.0.0`.

## 8.2 Banco nao sobe ou app trava no startup

Verificar:

- `DATABASE_URL` ou variaveis `PG*` do ambiente local;
- alcance de rede e `sslmode`;
- se `wait_for_db.py` esta estourando timeout;
- se o banco de destino realmente existe.

## 8.3 MWL nao responde

Verificar:

- `WORKLIST_AE_TITLE`;
- `WORKLIST_PORT`;
- se o processo `raiox_pacs.worklist_server` esta rodando;
- se os exames estao em estado elegivel para MWL (`scheduled`, `arrived`, `started`).

## 8.4 PACS DICOM nao recebe estudos

Verificar:

- `PACS_AET`;
- `DICOM_PORT`;
- regras de firewall;
- logs do PACS;
- permissao de escrita no `imagebox`.

## 8.5 Viewer sem previews

Verificar:

- se o objeto DICOM foi salvo em disco;
- se `public.objects.filepath` aponta para um arquivo valido;
- se o runtime ainda existe no host atual;
- se o estudo ja foi catalogado.

## 8.6 Cameras em erro

Verificar:

- instalacao do `ffmpeg`;
- URL RTSP/HLS;
- transporte `tcp` ou `udp`;
- permissao de escrita em `runtime/imagebox` e `runtime/backups`.

## 8.7 Portal `/docs` nao abre corretamente

Verificar:

- acesso por `/docs/index.html`;
- existencia dos arquivos em `docs/`;
- se o backend esta servindo `/docs/<path:filename>`;
- cache antigo do navegador, quando houver mudanca de assets locais.

## 9. Publicacao opcional no Render

Fluxo recomendado:

1. conectar o repositorio;
2. usar `render.yaml`;
3. definir `DATABASE_URL`, `APP_SECRET_KEY`, `RUNTIME_ROOT` e `PACS_WEB_URL` apenas se for usar banco externo;
4. publicar somente o cockpit web;
5. apontar PACS/MWL externos na tela `Config` se as portas DICOM nao puderem ser expostas.

Observacao importante:

- em hospedagens HTTP puras, o normal e deixar apenas o web publicado;
- PACS DICOM e MWL podem viver em outro host da rede da clinica.

## 10. Publicacao por GitHub

Fluxo simples:

```bash
git status
git add .
git commit -m "Sua mensagem"
git push
```

Fluxo mais seguro:

1. gerar backups;
2. validar ambiente em homologacao;
3. subir commit para a branch controlada;
4. deixar o hook/CI disparar o deploy.

## 11. Atualizacao segura

Antes de atualizar:

- congelar mudancas operacionais mais criticas;
- gerar backup;
- validar `PORT`, banco e runtime;
- revisar se a documentacao em `/docs` tambem foi atualizada quando houver mudanca arquitetural.

Depois de atualizar:

- validar dashboard;
- abrir um workspace de exame;
- confirmar PACS/MWL, backups e painel;
- revisar `Docs` para garantir que o portal continua servindo os arquivos corretamente.

## 12. Resumo operacional

Manter o raioXPacs saudavel significa manter coerentes:

- banco;
- storage;
- bind HTTP em `PORT`;
- topologia PACS/MWL;
- backups;
- documentacao local em `/docs`.

## 13. Atualizacao da interface

Com a revisao recente:

- a aba `Config` passou a usar submenus e mostra apenas um painel por vez;
- os status de banco, PACS e worklist ficam apenas dentro de `Config`;
- a importacao SQL manual saiu da interface, porque o bootstrap ja carrega o seed automaticamente;
- o botao `Sincronizar PACS` continua sendo a forma pratica de refrescar os espelhos locais e o estado de homologacao.
