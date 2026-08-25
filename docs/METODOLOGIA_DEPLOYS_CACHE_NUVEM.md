# Metodologia de deploys locais, cache AlwaysData e portal Render

Versao: 1.0
Data: 25/08/2026
Responsavel tecnico: Nanotech

## 1. Objetivo

Manter cada cliente operando de forma independente na rede local, distribuir o
codigo central pelo GitHub e oferecer uma interface de consulta em nuvem sem
permitir que o Render altere ou acesse diretamente os ambientes locais.

Esta metodologia separa quatro responsabilidades:

- GitHub: codigo, historico e versoes;
- deploy local: operacao completa e banco oficial do cliente;
- AlwaysData: cache de consulta recebido dos clientes;
- Render: interface central estritamente somente leitura.

## 2. Arquitetura oficial

```text
                         GitHub
                            |
             codigo versionado por tag/commit
                            |
        +-------------------+-------------------+
        |                   |                   |
   Rio Branco          Laboratorio          Senhor/Nanotech
   deploy local         deploy local          deploy local
   banco oficial        banco oficial         banco oficial
        |                   |                   |
        +------- envio unidirecional autorizado+
                            |
                     AlwaysData
              caches separados por cliente
                            |
                   usuario somente SELECT
                            |
                         Render
              interface de consulta em nuvem
```

O Render nao entra na Tailscale dos clientes, nao conhece credenciais dos
bancos locais e nao encaminha requisicoes para as aplicacoes locais. Se uma
alteracao for necessaria, o operador acessa o deploy local pela Tailscale.

## 3. Fonte de verdade e fluxo dos dados

O banco local de cada cliente e a unica fonte oficial. O sentido permitido e:

```text
banco local -> processo local de cache -> AlwaysData -> Render (SELECT)
```

Os sentidos abaixo sao proibidos:

```text
Render -> banco local
AlwaysData -> sobrescrever banco local
update.sh -> sincronizar ou restaurar dados
GitHub -> transportar banco, backup ou credencial
```

O cache pode ficar temporariamente atrasado sem interromper a operacao local.
Cada sincronizacao registra cliente, dataset, quantidade de linhas, instante do
snapshot e instante de publicacao. O endpoint `/healthz/cache` informa a idade
de cada dataset e usa `NS_CACHE_MAX_AGE_SECONDS` como limite de atualidade.

## 4. Isolamento dos clientes

Use um database/schema separado por cliente no AlwaysData:

- `cache_nanotech`
- `cache_riobranco`
- `cache_laboratorio`
- `cache_senhor`

Cada cliente recebe um usuario de escrita limitado exclusivamente ao proprio
cache. O Render recebe outro usuario, com somente `SELECT` nos caches que a
Nanotech autorizou. Nunca reutilize no Render a credencial usada pelo processo
de sincronizacao.

O campo `NS_CACHE_DATABASE_MAP` informa ao portal quais caches podem ser
consultados pela mesma interface. Exemplo de valor no painel do Render:

```json
{"rio-branco":"cache_riobranco","laboratorio":"cache_laboratorio","senhor":"cache_senhor","nanotech":"cache_nanotech"}
```

`NS_DB_NAME` permanece sendo o database de autenticacao/cache administrativo.
O seletor no portal muda apenas o database de consulta operacional. O usuario
MySQL do Render precisa de `SELECT` em todos os databases listados no mapa.

## 5. Perfis de deploy

Os perfis ficam em `deploy/profiles.json` e sao selecionados por
`NANOTECH_DEPLOY_PROFILE`.

| Perfil | Cliente | Banco local | RioB local | Tailscale | Papel |
|---|---|---:|---:|---:|---|
| `nanotech` | Nanotech | sim | sim | sim | administracao completa |
| `rio-branco` | Rio Branco | sim | sim | sim | producao contratada |
| `laboratorio` | Laboratorio | sim | nao neste repo | sim | PACS em deploy/repositorio proprio |
| `senhor` | Senhor | sim | nao | sim | Store e modulos contratados |
| `render` | Nanotech Nuvem | nao | nao | nao | consulta ao cache |

Os scripts bloqueiam a execucao quando `CLIENTE_DEPLOY_ID` diverge do cliente
definido pelo perfil. Isso evita publicar acidentalmente o conjunto de modulos
de uma empresa em outra.

Exemplo local:

```bash
NANOTECH_DEPLOY_PROFILE=senhor ./up.sh
NANOTECH_DEPLOY_PROFILE=senhor ./update.sh main
```

`update.sh` continua sem iniciar, parar, importar, exportar, restaurar ou
sincronizar bancos.

## 6. Codigo central no GitHub

O GitHub distribui somente codigo e configuracao versionavel. O fluxo normal e:

```text
desenvolvimento Nanotech
  -> teste local
  -> commit e push seguro
  -> tag/commit aprovado
  -> update individual de cada cliente
```

Cada deploy pode atualizar no momento adequado e manter apenas os modulos do
seu contrato. Banco, anexos, dumps, `.env`, certificados e tokens nao entram no
Git.

O PACS e uma excecao de propriedade de codigo: sua versao global permanece no
repositorio e deploy do Laboratorio. Este repositorio nao contem uma copia. Os
perfis Nanotech/Laboratorio podem exibir somente um atalho definido por
`LABORATORIO_PACS_URL`.

## 7. Render somente leitura

O `render.yaml` fixa:

```text
CLIENTE_DEPLOY_ID=cloud
NS_DEPLOY_MODE=cloud-readonly
NS_READ_ONLY=1
NS_CACHE_PROVIDER=alwaysdata
RIOB_PROXY_ONLY=1
```

Defesas aplicadas pela aplicacao:

- bloqueio de `POST`, `PUT`, `PATCH` e `DELETE` de negocio;
- excecao apenas para login/logout da sessao web;
- ausencia de bootstrap, seed ou migracao de schema;
- coletor do modulo Tecnologia desativado;
- banner permanente de somente leitura;
- cabecalho `X-Nanotech-Read-Only: 1`;
- contrato `cloud` limitado aos modulos preparados para consulta;
- nenhuma `RIOB_BASE_URL` local no Blueprint.

A permissao `SELECT` no MySQL e a segunda barreira. O bloqueio da aplicacao nao
substitui a configuracao correta de grants no AlwaysData.

## 8. Preparacao do cache

Crie cada database de cache e aplique o schema compatível antes da primeira
sincronizacao. Essa preparacao e uma operacao de dados separada, executada por
um administrador do AlwaysData. Nao coloque senhas no comando, no Git ou nesta
documentacao.

O sincronizador exige que as colunas da tabela local e da tabela de cache sejam
iguais. Ele nao cria tabelas de negocio automaticamente. Somente a tabela de
controle `cloud_cache_status` e criada pelo proprio processo.

O AlwaysData oferece MariaDB/MySQL remoto, usuarios com permissoes separadas e
restricao por IP. Consulte a documentacao oficial:

- <https://help.alwaysdata.com/en/docs/web-hosting/databases/mariadb/>
- <https://help.alwaysdata.com/en/docs/technical-specifications/drp/>

## 9. Sincronizacao local para o cache

A ferramenta autorizada e `tools/cloud_cache_sync.py`. Ela nao e chamada pelos
quatro comandos canonicos, pelo startup ou pelo auto-deploy.

Variaveis obrigatorias no cliente:

```text
CACHE_SOURCE_DB_HOST
CACHE_SOURCE_DB_PORT
CACHE_SOURCE_DB_USER
CACHE_SOURCE_DB_PASSWORD
CACHE_SOURCE_DB_NAME
CACHE_TARGET_DB_HOST
CACHE_TARGET_DB_PORT
CACHE_TARGET_DB_USER
CACHE_TARGET_DB_PASSWORD
CACHE_TARGET_DB_NAME
CACHE_SYNC_CLIENT_ID
CACHE_SYNC_DATASET
CACHE_SYNC_TABLES
```

A ferramenta carrega `NANOTECH_ENV_FILE`, `.env` ou `.env_local` na mesma ordem
basica do portal. Esses arquivos permanecem ignorados pelo Git.

`CACHE_SYNC_TABLES` e uma lista explicita. Para o contrato de nuvem atual do
portal, um conjunto inicial pode incluir:

```text
usuarios,portal_config,installed_apps,usuario_app_permissoes,
financeiro_registros,financeiro_config,
tecnologia_dispositivos,tecnologia_velocidade,tecnologia_metricas,
tecnologia_alertas_recursos,
chamados,chamados_intervencoes,chamados_documentos
```

Quebras de linha devem ser removidas ao colocar o valor no `.env`. Como
`usuarios` possui hash de senha, sua inclusao exige avaliacao e
`CACHE_SYNC_ALLOW_SENSITIVE=1`. Prefira um cache administrativo dedicado e
senhas fortes; nunca replique tokens SMTP, chaves fiscais ou senhas de
integracoes.

Primeiro valide sem gravar:

```bash
python3 -m tools.cloud_cache_sync --dry-run
```

Depois, somente no cliente autorizado:

```bash
CACHE_SYNC_ENABLED=1 python3 -m tools.cloud_cache_sync --yes
```

O destino deve comecar com `cache_`. O programa bloqueia origem e destino
iguais, exige lista de tabelas, valida schemas, usa lotes e substitui cada
snapshot dentro de uma transacao no cache. Falhas executam rollback no destino
e nunca escrevem na origem.

Para automatizar, use o agendador do sistema operacional do cliente somente
depois de uma execucao manual validada. Grave logs fora do Git e alerte quando
o comando falhar ou `/healthz/cache` ultrapassar a idade maxima.

## 10. Frequencia e disponibilidade

Sugestao inicial:

- dados operacionais: a cada 5 ou 15 minutos;
- cadastros pouco alterados: a cada 30 ou 60 minutos;
- backup completo: diariamente, fora do sincronizador de cache;
- teste de restauracao: mensal, em ambiente isolado.

Se a frequencia for 15 minutos, o objetivo de perda de atualizacao do cache
(RPO de consulta) e de ate 15 minutos, mais o tempo de execucao. Isso nao altera
o RPO do backup. Se o AlwaysData ou a internet falhar, o cliente continua
operando localmente e o Render deve sinalizar cache desatualizado.

## 11. Cache nao e backup

O snapshot do AlwaysData acompanha o estado atual e pode refletir exclusoes.
Por isso ele nao substitui uma politica de backup. Mantenha separadamente:

- dumps criptografados por cliente;
- retencao diaria, semanal e mensal conforme contrato;
- checksum e registro de sucesso;
- copia fora do servidor local;
- restore testado em banco isolado;
- promocao de contingencia manual e documentada.

Nunca restaure o AlwaysData sobre um banco local automaticamente. Em
contingencia, escolha um cliente, valide o backup, restaure em instancia
isolada, aprove a promocao e altere somente a rota daquele cliente.

## 12. Seguranca

- TLS nas conexoes MySQL remotas sempre que suportado;
- um usuario escritor por cliente e por cache;
- um usuario leitor exclusivo do Render;
- restricao por IP quando operacionalmente possivel;
- secrets apenas no `.env` local ou painel do provedor;
- nenhuma credencial em Git, PDF, logs ou prints;
- dados pessoais e anexos somente quando necessarios para a consulta;
- revisao da LGPD e do prazo de retencao antes de incluir novas tabelas;
- auditoria dos datasets, quantidades e horarios de sincronizacao.

## 13. Validacao operacional

No cliente:

```bash
NANOTECH_DEPLOY_PROFILE=rio-branco ./up.sh
python3 -m tools.cloud_cache_sync --dry-run
```

No Render:

```text
GET /healthz
GET /healthz/database
GET /healthz/cache
```

Resultados esperados:

- `deploymentMode` igual a `cloud-readonly`;
- `readOnly` igual a `true`;
- banco administrativo acessivel;
- datasets com `fresh=true`;
- tentativa de gravacao retorna HTTP 403 e `cloud_read_only`;
- nenhum acesso do Render aparece nos bancos ou servicos Tailscale locais.

## 14. Implantacao em fases

1. Criar usuarios e databases separados no AlwaysData.
2. Aplicar schema vazio e grants minimos.
3. Configurar um cliente piloto e executar `--dry-run`.
4. Fazer o primeiro snapshot e conferir quantidades somente por leitura.
5. Configurar o mapa de caches e a credencial `SELECT` no Render.
6. Validar bloqueio de escrita e atualidade do cache.
7. Habilitar agendamento no cliente piloto.
8. Repetir cliente por cliente, sem sincronizacoes simultaneas no primeiro ciclo.
9. Implantar backups independentes e testar restauracao.

## 15. Decisao final

A Nanotech e o plano de controle; os clientes continuam soberanos sobre seus
dados locais; o GitHub centraliza o codigo; o AlwaysData fornece caches
isolados; e o Render fornece uma URL unica de consulta. Nenhum desses papeis
deve ser misturado com deploy comum ou restauracao automatica.
