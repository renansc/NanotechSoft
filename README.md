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

Abra `http://127.0.0.1:5600`. Na rede local, o portal tambem fica disponivel
em `https://192.168.200.254` pela porta `443`; instale primeiro a CA interna
oferecida em **NanoStore > Configuracao > HTTPS e camera** para liberar a camera
do celular em um contexto seguro.

## Banco com Docker

```bash
cd NanotechSoft
cp .env.example .env
docker compose up -d mysql
```

Esse compose publica o MySQL do portal na porta `3307`, para nao conflitar com
um MySQL local padrao.

Dentro da rede Docker, o portal acessa:

- MySQL do portal: `mysql:3306`.

De fora do Docker, use:

- MySQL do portal: `127.0.0.1:3307`.

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

No Render, use o `render.yaml`; as variaveis `NS_DB_*` devem apontar para o
cache AlwaysData com um usuario que possua somente `SELECT`.

## Deploy no Render

A branch `main` contem tambem a configuracao externa. O `render.yaml` define o
Web Service:

- `nanotechsoft`: web service Docker do portal.

No Render, importe o Blueprint a partir da branch `main`. Criar apenas um
Web Service manual exige a configuracao equivalente das variaveis no painel.

O perfil do Blueprint e fixo em `CLIENTE_DEPLOY_ID=cloud`,
`NS_DEPLOY_MODE=cloud-readonly`, `NS_READ_ONLY=1` e
`NS_CACHE_PROVIDER=alwaysdata`. Nesse modo:

- o Render nao acessa bancos, URLs ou APIs locais pela Tailscale;
- o Render nao inicia RioB nem outros servicos operacionais locais;
- toda requisicao de negocio `POST`, `PUT`, `PATCH` ou `DELETE` e recusada;
- apenas login/logout de sessao sao aceitos por `POST`;
- o startup nao cria banco, nao aplica schema e nao semeia registros;
- o modulo Tecnologia consulta o cache, mas nao inicia coletores;
- `NS_DB_*` usa a credencial de leitura do cache AlwaysData.

Cada cliente continua sendo a fonte oficial dos proprios dados. Um processo
separado no cliente envia snapshots autorizados ao AlwaysData no sentido unico
`local -> cache`. Esse processo nao faz parte de `up.sh` nem `update.sh`.
Consulte `docs/METODOLOGIA_DEPLOYS_CACHE_NUVEM.md` para configuracao, seguranca,
retencao e contingencia.

### Validacao obrigatoria do Render somente leitura

Antes de considerar uma alteracao concluida:

1. confirme que o commit esperado esta em `origin/main`;
2. confirme no Render que esse mesmo commit terminou o deploy;
3. teste `/healthz`, `/healthz/database` e `/healthz/cache` pela URL publica;
4. confirme que uma requisicao de escrita retorna `403` com
   `code=cloud_read_only`;
5. confirme, somente com consultas de leitura, que o cache contem os registros
   esperados e que `syncedAt` esta dentro da janela configurada;
6. trate backup, restore ou sincronizacao de dados como operacao separada,
   explicitamente autorizada e nunca como efeito colateral do deploy.

Um `200` em `/healthz` comprova apenas que o portal esta respondendo.
`/healthz/cache` valida a existencia e a atualidade registrada dos datasets.

Configure o servidor MySQL unico no Web Service do Render com estas variaveis:

- `NS_DB_HOST`
- `NS_DB_PORT`
- `NS_DB_USER`
- `NS_DB_PASSWORD`
- `NS_DB_NAME`

O usuario definido em `NS_DB_USER` no Render deve receber apenas permissao de
leitura. A credencial de escrita usada pelo sincronizador local e diferente e
nunca deve ser configurada no Render.

### Backup JSON pelo navegador

A tela `Config` possui um painel `Backup do portal` para administradores. Ele
exporta todas as tabelas do banco principal para um arquivo JSON e permite
importar esse JSON de volta para o MySQL atual.

Esse recurso existe somente nos ambientes locais gravaveis. No Render, a
importacao e bloqueada pelo modo somente leitura. Em ambiente local, baixe o
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

- `./up.sh` reconstrói e sobe os serviços habilitados no perfil, preservando bancos e volumes.
- `./down.sh` para os serviços do perfil sem parar, restaurar ou sincronizar bancos.
- `./update.sh` atualiza o código e recria somente as aplicações habilitadas, sem operar bancos.
- `./git-safe-push.sh` bloqueia arquivos sensíveis/runtime, valida o perfil, cria o commit e envia a branch atual para `origin`.

Os perfis versionados ficam em `deploy/profiles.json`. Selecione um deles com
`NANOTECH_DEPLOY_PROFILE`: `nanotech`, `rio-branco`, `laboratorio`, `senhor` ou
`render`. O perfil define o cliente, se existe banco local e se a pilha RioB
deve ser operada; ele nao define credenciais.

A matriz global de componentes e ambientes fica em `deploy/ecosystem.json`.
Ela mantém o Portal neste repositório e referencia o PACS principal no
`renansc/RisPacsFull`, além de registrar o catálogo mínimo do Nanotech e a janela
de atualização do Senhor após 18h. Consulte
`docs/ECOSSISTEMA_DEPLOYS.md`.

Não existem scripts operacionais próprios dentro dos apps. Consulte
`docs/AI_RESEARCH_MANUAL.md` para os contratos completos e pressupostos
permanentes do projeto.

Os scripts detectam `docker compose`, `docker-compose` ou `podman compose`. Se o Docker CLI nao estiver disponivel no terminal atual, execute os scripts fora de sandboxes que nao exponham Docker, como alguns ambientes Flatpak, ou instale o plugin Compose.

Em um ambiente sem Docker CLI, o `./git-safe` pula Compose/build/health automaticamente e ainda roda as validacoes de Python, manifests e clientes. Use `--skip-compose` quando quiser deixar esse pulo explicito. Use `--skip-whitespace` somente quando precisar ignorar `git diff --check`; por padrao, vendors minificados e binarios ja sao excluidos dessa checagem. Se faltarem dependencias Python locais, a validacao que importa `app.py` vira aviso; instale `requirements.txt` para checar tambem rotas e temas fora do container.

## Apps dinamicos

Os apps ficam dentro de `apps/`. Cada subpasta pode ter um `app.json`; tambem existe a tabela `installed_apps` para cadastro via banco.

O módulo **Tecnologia** monitora o link, o roteador, servidores, NVR, relógio
ponto e impressoras. Além de ICMP/TCP, mede download/upload do link e aceita
SNMP ou exporters Prometheus para CPU, memória, disco e rede. Mantém histórico
de 90 dias e oferece descoberta manual de impressoras e computadores
Windows/Linux por ICMP, NetBIOS e portas de serviço. Ao clicar em um equipamento,
um card apresenta as métricas e a identificação recebidas do exporter. Um mesmo
equipamento pode ter IP principal e endereços adicionais para cabo, Wi-Fi ou
Tailscale; a coleta escolhe automaticamente um caminho disponível. A coleta
começa quando o módulo é aberto. Queda ou velocidade baixa da internet e uso
acima de 90% de CPU, memória, disco ou capacidade de rede podem enviar alertas
por SMTP. Falhas do gateway também enviam e-mail; os demais equipamentos
internos ficam somente no painel. Por padrão, o remetente é uma conta
de e-mail já configurada no RioB e `TECH_ALERT_EMAIL_TO` define somente o
destinatário; a substituição opcional por `SMTP_*` fica documentada no README
do módulo. Consulte
`apps/tecnologia/README.md` para os limites do diagnóstico de Wi-Fi e a operação.

O módulo **Chamados** registra requisições e manutenções de TI, predial,
elétrica e outras áreas. Ele reutiliza os usuários do portal e os equipamentos
do módulo Tecnologia, mantém intervenções com tempo gasto, exige uma medida
resolutiva ao concluir e consulta casos semelhantes já resolvidos. Manuais,
links e anexos podem ser gerais ou vinculados a equipamento/chamado. A agenda
do módulo programa tarefas, reuniões, orçamentos e retornos com aviso por e-mail
usando o SMTP local. Os cadastros automáticos de rede do Rio Branco são criados
somente no perfil `rio-branco`, sem contaminar ambientes Nanotech novos. Consulte
`apps/chamados/README.md` para o fluxo e as rotas.

O arquivo `clientes-modulos.json` define os clientes e quais modulos cada um possui. No deploy local, `NANOTECH_DEPLOY_PROFILE` seleciona tambem o `CLIENTE_DEPLOY_ID`; configuracoes divergentes sao bloqueadas. Cada ambiente continua usando seu proprio banco via `NS_DB_NAME`/credenciais, sem misturar dados entre clientes. Modulos com `status=externo` usam a URL indicada por `hrefEnv`, como `LABORATORIO_PACS_URL`, sem copiar seu codigo para este repositorio.

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

Excluir um app do contrato de um cliente apenas o desabilita naquele perfil; o
código global não deve ser apagado. A exceção é o PACS, mantido como componente
externo no repositório próprio do Laboratório.

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
As rotas `/apps/<app_key>` tambem validam essa permissao no servidor, inclusive
quando o endereco e digitado diretamente. Webhooks, uploads e compartilhamentos
marcados como publicos pelas integracoes permanecem acessiveis sem sessao.

## Financeiro

O app financeiro fica em `apps/financeiro` e roda integrado ao shell do NanotechSoft. Os dados foram migrados do backup JSON inicial para MySQL nas tabelas `financeiro_registros` e `financeiro_config`.

O Dashboard Financeiro e as telas de Contas a Pagar e Contas a Receber possuem a ação **Imprimir PDF**. Os relatórios mantêm a conta, o período, o status e a busca atualmente selecionados. Em Contas a Pagar e Contas a Receber, os PDFs anexados aos títulos ou aos lançamentos vinculados são acrescentados ao final do relatório em um único arquivo, sem duplicar um mesmo anexo físico. O dashboard continua usando a caixa de impressão do navegador.

Na tela **Importar Extrato**, o histórico de importações permite trocar a conta de um lote inteiro ou excluir somente as transações bancárias daquela importação. A troca acompanha lançamentos, títulos e compras vinculados; a exclusão remove as conciliações, mas preserva os registros do sistema, deixando-os desvinculados para evitar perda acidental.

Na **Conciliação**, os matches confirmados são a fonte única do vínculo banco-lançamento. As criações em lote ignoram transações já vinculadas ou com candidato similar, e títulos não podem tomar uma transação pertencente a outro lançamento. Ao carregar estados gravados por versões anteriores, o app restaura vínculos parciais e cancela somente títulos/lançamentos comprovadamente duplicados que tenham sido gerados do próprio extrato.

O tema padrao do portal continua sendo `Rio Branco`. O tema original do financeiro fica disponivel como `Fin Blue`; nenhum deles e aplicado automaticamente ao abrir um app.
