# Arquitetura da Laboratorio Santa Terezinha

## 1. Visao geral

A Laboratorio Santa Terezinha opera um cockpit unico de RIS e PACS, reunindo:

- cadastro clinico e financeiro, com submenu Cadastros para Pacientes e Exames;
- operacao do fluxo do exame;
- worklist DICOM local;
- PACS DICOM proprio;
- viewer com anexos e objetos DICOM;
- compartilhamento externo com login;
- chat interno por departamentos e painel de chamadas;
- monitoramento de storage e backups.

O projeto foi estruturado para funcionar em dois cenarios:

1. **modo local/integrado**: o proprio projeto sobe interface web, banco, PACS DICOM e MWL;
2. **modo web-only**: a interface HTTP fica publicada separadamente e os endpoints PACS/MWL podem ser apontados como
   externos pela tela `Config`.

## 2. Componentes executaveis

| Componente | Entrada principal | Papel |
| --- | --- | --- |
| Web Flask | `app.py` + `raiox_pacs/app_factory.py` | Entrega a interface HTML e a API JSON |
| Gunicorn | `docker/entrypoint.sh` ou `render.yaml` | Publica a interface web em `PORT` ou `APP_PORT` |
| Bootstrap de schema | `raiox_pacs/bootstrap.py` | Cria/atualiza tabelas `raiox.*` e estruturas `public.*` |
| Banco | `raiox_pacs/db.py` | Abre conexoes `psycopg` com `DATABASE_URL` ou `PG*` |
| Servico clinico | `raiox_pacs/services.py` | Regra de negocio principal do cockpit |
| PACS DICOM | `raiox_pacs/dicom_server.py` | Implementa `C-ECHO`, `C-STORE`, `C-FIND`, `C-GET`, `C-MOVE` |
| MWL DICOM | `raiox_pacs/worklist_server.py` | Implementa `Modality Worklist C-FIND` |
| Catalogo PACS | `raiox_pacs/pacs_catalog.py` | Persiste/consulta estudos, series e objetos DICOM |
| Runtime de midias | `raiox_pacs/camera_runtime.py` | Mantem o fluxo legado de midias locais quando necessario |
| Portal de docs | `docs/` + rota `/docs` | Viewer HTML da documentacao Markdown e dos diagramas |

## 3. Camadas da aplicacao

### 3.1 Interface web

- `templates/index.html` concentra o shell principal do cockpit;
- `templates/login.html` faz a selecao inicial do departamento;
- `static/app.js` e um frontend sem build separado, carregado diretamente pelo navegador;
- `static/style.css` define o visual do cockpit;
- `templates/viewer.html` e `templates/share_login.html` suportam o portal de visualizacao/compartilhamento.

### 3.2 Backend HTTP

`raiox_pacs/app_factory.py` monta o app Flask e:

- carrega configuracao;
- instancia banco e runtime de midias;
- publica HTML, midias, `/docs` e a API JSON;
- usa `ClinicService` para encapsular as regras de negocio.

### 3.3 Camada de negocio

`raiox_pacs/services.py` centraliza:

- cadastro de pacientes, procedimentos, exames e operadores;
- mudanca de etapas do exame e sincronizacao com a worklist;
- laudos, anexos, viewer e compartilhamento externo;
- configuracao de integracoes PACS/MWL/Web;
- financeiro, chat, painel e backups.

### 3.4 Persistencia e protocolos

- `raiox_pacs/db.py` encapsula conexoes com PostgreSQL;
- `raiox_pacs/bootstrap.py` garante que o schema exista;
- `raiox_pacs/pacs_catalog.py` persiste o catalogo PACS nas tabelas `public.study`, `public.series` e `public.objects`;
- `raiox_pacs/worklist_server.py` serve a fila da MWL a partir de `raiox.exam`;
- `raiox_pacs/dicom_server.py` atende Store/Query/Retrieve usando `pynetdicom`.

## 4. Pastas principais

```text
RaioxPacs/
|- app.py
|- requirements.txt
|- Dockerfile
|- docker-compose.yml
|- render.yaml
|- docs/
|  |- index.html
|  |- documentacao.html
|  |- diagramas.html
|  |- *.md
|  |- vendor/
|- docker/
|  |- entrypoint.sh
|  |- init/
|- scripts/
|  |- bootstrap_db.py
|  |- wait_for_db.py
|  |- deploy/
|- raiox_pacs/
|  |- app_factory.py
|  |- bootstrap.py
|  |- config.py
|  |- db.py
|  |- services.py
|  |- pacs_catalog.py
|  |- dicom_server.py
|  |- worklist_server.py
|  |- camera_runtime.py
|- templates/
|- static/
|- runtime/
```

## 5. Configuracao e descoberta de ambiente

`raiox_pacs/config.py` resolve a configuracao a partir de:

- `.env` no root do projeto, quando existir;
- `DATABASE_URL` ou variaveis `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`;
- `PORT` com fallback para `APP_PORT`;
- `RUNTIME_ROOT` para definir onde imagebox e backups vivem;
- parametros DICOM/MWL, SIP, painel e compartilhamento.

Pontos arquiteturais importantes:

- a interface web segue `PORT` primeiro, para funcionar bem em PaaS;
- `PACS_WEB_URL` e `RENDER_EXTERNAL_URL` influenciam URLs externas e compartilhamentos;
- `AUTO_BOOTSTRAP_SCHEMA=1` faz o schema nascer automaticamente no startup.

## 6. Modelo de integracao

O sistema tem tres frentes de integracao principais:

### 6.1 Banco

- pode usar PostgreSQL local ou remoto;
- `Database.connection_kwargs()` normaliza conexao a partir de `DATABASE_URL` ou `PG*`;
- `sslmode` pode ser sobrescrito com `PGSSLMODE`.

### 6.2 PACS

- em modo local, o proprio `dicom_server.py` atende `Verification`, `Storage` e `Study Root Query/Retrieve`;
- em modo externo, a interface continua funcionando e mostra status do alvo efetivo na lateral e na tela `Config`.

### 6.3 Worklist

- em modo local, `worklist_server.py` expande exames do schema `raiox` em datasets MWL;
- em modo externo, o cockpit passa a apontar um MWL remoto configurado em `Config`.

## 7. Runtime e storage

O projeto usa `runtime/` como raiz operacional. Dentro dele, o mais importante e:

- `runtime/imagebox`: storage das imagens DICOM persistidas;
- `runtime/backups` ou derivacoes similares: arquivos operacionais de backup.

Arquiteturalmente, o viewer e o backup dependem desse runtime:

- o viewer busca anexos e previews a partir das rotas web;
- o catalogo PACS referencia o `filepath` real dos objetos;
- a tela `Storage` calcula ocupacao do disco e lista pacotes de backup.

## 8. Estados do exame

O fluxo principal do exame usa `workflow_stage` e estados correlatos. Os estagios disponiveis hoje sao:

| Chave | Significado operacional |
| --- | --- |
| `draft` | cadastro inicial antes da publicacao em worklist |
| `scheduled` | publicado/espelhado na MWL local |
| `arrived` | paciente chegou |
| `started` | exame em execucao |
| `executed` | aquisicao concluida |
| `reporting` | exame em laudo |
| `finalized` | laudo concluido |
| `cancelled` | exame cancelado |
| `removed` | retirado da worklist/local flow |

Esse fluxo aparece em:

- Dashboard;
- Kanban;
- telas de exames e worklist;
- automacoes de laudo e compartilhamento;
- espelhamento da fila para o MWL local.

## 9. Compartilhamento e viewer

O viewer interno e o compartilhamento externo compartilham a mesma base de midia:

- anexos web enviados ao exame;
- objetos DICOM catalogados no PACS;
- previews PNG gerados sob demanda;
- laudos e dados clinicos do workspace.

A area de compartilhamento externo tem uma protecao propria:

- slug publico;
- username e senha por compartilhamento;
- sessao Flask associada ao slug;
- controle separado para anexos e previews autorizados.

## 10. Comunicacao e painel

O mesmo cockpit inclui dois subsistemas operacionais que costumam ficar dispersos em outros projetos:

### 10.1 Chat por departamentos

- a entrada inicial usa login por departamento;
- departamentos predefinidos para recepcao, sala de raio-x e ultrassom;
- conversas por setor;
- contagem de mensagens nao lidas por departamento.

### 10.2 Painel de chamadas

- cada exame pode gerar senha/fila;
- chamadas sao publicadas na tela do painel;
- o painel suporta video e anuncio por voz;
- destinos configuraveis permitem chamar para recepcao, salas e setores.


## 11. Documentacao incorporada

No mesmo padrao do app Rio Branco, o raioXPacs agora serve um portal HTML local:

- `/docs`
- `/docs/index.html`
- `/docs/documentacao.html`
- `/docs/diagramas.html`

Esse portal e parte da arquitetura da aplicacao, nao um artefato externo. Com isso:

- a documentacao fica versionada junto do codigo;
- os fluxogramas abrem no navegador sem ferramenta adicional;
- a equipe consegue navegar entre arquitetura, runbook e API usando o proprio sistema.

## 12. Pontos de atencao arquiteturais

### 12.1 Autenticacao interna

A cockpit principal usa uma autenticacao leve por departamento na tela `login` e guarda a escolha na sessao Flask.
A alteracao da aba `Config` exige a senha admin `St12356!`.

### 12.2 Dependencias de ambiente

- DICOM e MWL dependem de portas especificas e, em nuvem, podem precisar ficar externos;
- backups de banco preferem `pg_dump`, mas o sistema possui fallback logico quando necessario.

### 12.3 Bootstrap no startup

O startup do web app, do PACS e da MWL depende do banco para `ensure_schema()`. Em ambiente PaaS, falhas de banco
podem se manifestar como timeout de subida da aplicacao.

## 13. Resumo executivo

Arquiteturalmente, o raioXPacs e um monolito pragmatico:

- **frontend leve** sem build;
- **backend Flask** com API e HTML;
- **regras de negocio centralizadas** em `services.py`;
- **persistencia em PostgreSQL** com schema clinico e tabelas PACS;
- **protocolos DICOM/MWL locais** quando o ambiente permite;
- **portal de documentacao incorporado** para reduzir dependencia de contexto tacito.
