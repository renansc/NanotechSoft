# Acessos por item do menu

Em **Configurar > Usuarios e acessos**, selecionar uma pessoa e marcar ou
desmarcar cada destino do menu. **Salvar usuario** grava as escolhas. A busca
filtra por nome da tela, modulo ou categoria. O controle vale para usuarios
comuns; administradores continuam com acesso integral. Usuarios e acessos,
Clientes e modulos e Backup do portal continuam exclusivos de administrador,
identificados dessa forma na lista.

A tela ocupa toda a largura disponivel. Os dados do usuario se adaptam de quatro
colunas no desktop para uma no celular; as permissoes aparecem em grupos por
modulo, com colunas conforme o espaco. A busca oculta os grupos sem resultados,
e a barra de salvar/excluir permanece acessivel durante a rolagem. Este ajuste
de apresentacao preserva o catalogo e as regras de autorizacao descritos abaixo.

O perfil Rio Branco possui 149 controles: RioB (77), Zap (16), Tecnologia (13),
Automacao (12), Email (10), XML (6), Sistema (6), Chamados (5) e Impressoras (4).
O [mapa completo](MAPA_ACESSOS_MENU.csv) identifica categoria, nome, destino,
chave individual e recurso anterior. Atalhos repetidos para o mesmo destino
compartilham um controle; as categorias aparecem juntas. Cada destino distinto
possui sua propria escolha, mesmo quando antes compartilhava uma permissao.

Exemplo: **Monitoramento de backups**, **Planos de backup** e **Instalar agentes
de backup** podem ser liberados separadamente. Desmarcar Instalar agentes
bloqueia esse destino mesmo se a permissao geral `tecnologia:backup` ou `*`
continuar marcada. A mesma regra vale para os demais itens.

Monitoramento de backups apresenta estado atual, falhas de contato e destinos
com `tecnologia:backup`, sem botoes para alterar planos. O catalogo explicita
essas consultas no recurso existente; a API compartilhada continua validando
acesso e bloqueios individuais. Nenhuma permissao nova e concedida.

## Implementacao e compatibilidade

- Impressoras possui quatro tarefas independentes: fila pessoal (`fila`),
  estado (`monitor`), auditoria geral (`historico`) e administracao CUPS
  (`gerenciar`). Liberar exige novamente a senha do usuario, sem persisti-la;
  cancelar trabalho alheio e alterar uma fila exigem `gerenciar`. Nenhuma
  concessao e criada ao instalar o modulo.

- ESTOQUE > RioB > Baixas por perda usa `estoque_perdas` para produtos/saldos,
  historico, conferencia e confirmacao. O proxy e o blueprint verificam esse
  recurso; `estoque` sozinho nao libera a nova funcao. Sessao unica, bloqueios
  individuais e modo somente leitura permanecem. Ver BAIXAS_POR_PERDA.md do RioB.

- Gestao > Tecnologia > Rede possui o recurso `tecnologia:rede` e escolha
  individual propria; `GET /apps/tecnologia/api/network` e `/network/<id>`
  respeitam essa escolha, inclusive bloqueios sobre `*`. Nao libera cadastro,
  sondas manuais ou outras telas, nem concede acessos automaticamente.
- `menu_access.py` deriva os controles dos `menu_groups` e `config_groups` do
  perfil ativo nos manifests. `portal.app.json` inclui os itens comuns do sistema.
- Relatorios > RioB > Vendas concentra as abas de vendas. `navigation_parent`
  identifica destinos acessiveis pelas abas: nao aparecem novamente no menu
  principal, inclusive para administradores, mas conservam suas chaves e
  escolhas em Usuarios e acessos. Vendas Diario usa
  `/api/vendas/diario/relatorio`, separado do dashboard do mes atual; o bloqueio
  individual de um nao libera nem bloqueia o outro.
  Quem possui somente uma aba liberada continua vendo uma unica entrada Vendas,
  que aponta para essa aba, sem ampliar a permissao para as demais.
- Grupos de embalagem usa o mesmo `riob:vendas` para o intervalo, resumo e
  filtro Grupos e popup Ver PDVs (lista e detalhe). O catalogo explicita ambos;
  destino, chave individual e API compartilhada permanecem os mesmos. Nenhuma
  concessao e criada; o servidor continua exigindo sessao, contrato e acesso.
- A chave `menu:<hash>` usa o destino normalizado, com os seletores de tarefa
  (`view`, `secao`, `painel`, `visao` e fragmento). Renomear ou mover o item entre
  categorias preserva a chave. Mudar seu destino exige revisar compatibilidade.
- A tabela existente `usuario_app_permissoes` guarda `permitido=1` para liberar
  e `permitido=0` para bloquear. O bloqueio individual prevalece sobre os recursos
  gerais. Sem escolha individual gravada, vale a regra anterior do recurso.
- `GET /api/usuarios` retorna `catalogo_acessos[].menus` e
  `usuarios[].permissoes_menu`. `POST/PUT /api/usuarios` aceita
  `permissoes_menu: {app_key: {chave_do_menu: true|false}}`. Omitir esse campo
  preserva todas as escolhas; enviar parte dele altera somente as chaves enviadas.
  Chaves desconhecidas e valores que nao sejam booleanos sao rejeitados.
- O payload anterior `permissoes` continua disponivel. As permissoes gerais e
  acoes internas existentes aparecem em uma secao recolhida. A atualizacao do
  codigo nao grava nem amplia concessoes. Salvar o formulario grava explicitamente
  as escolhas mostradas para a pessoa selecionada.
- O menu, a entrada inicial e o servidor consultam as escolhas. Rotas de paginas
  e APIs mapeadas em `api_destinations` validam a tarefa antes do encaminhamento.
  APIs de leitura compartilhadas podem atender varias telas liberadas; isso nao
  libera a escrita de uma tela irma. A autorizacao anterior continua nas rotas
  sem mapeamento individual e nas acoes internas, como finalizar contagem.
- Fragmentos `#...` nao chegam ao servidor HTTP. `static/menu-access.js` bloqueia
  a tela no navegador e suas transicoes; o servidor verifica as APIs associadas.
  RioB recebe o mesmo bloqueio dentro do frame. O atalho antigo `#backup` de
  Tecnologia corresponde a `#backup-visao`.
- Sessao unica, contrato do deploy, operacoes exclusivas de administrador e modo
  somente leitura da nuvem permanecem obrigatorios.

Este cadastro controla itens de menu. Botoes e operacoes internas continuam
vinculados a suas telas e as restricoes existentes.

## Manutencao e verificacao

Gestao > Manutencoes inclui a previa e a importacao TXT/CSV de notas manuais.
As rotas `POST /api/manutencoes/importacoes-txt/preview` e `POST
/api/manutencoes/importacoes-txt` exigem o mesmo item individual
`/apps/riob#gestaofrota:manutencao`, recurso herdado `frota`. A alteracao nao
concede acesso automaticamente; bloqueios individuais continuam prevalecendo.

Gestao > Tecnologia > Rede possui a acao interna **Buscar dispositivos**, com
recurso proprio `tecnologia:rede_scan` no catalogo de Config > Usuarios e acessos.
Exige tambem acesso ao item Rede; o bloqueio individual de Rede prevalece sobre
a concessao da acao. O POST `network/scan` somente consulta a rede privada local,
nao cadastra nem monitora resultados e e bloqueado no Render. A concessao nao e
automatica; administradores/acesso integral preservam as regras existentes.

Ao alterar um menu, atualizar seu manifest, documentacao e, quando houver novas
APIs, o relacionamento com a tela no servidor. Gerar o mapa com
`python3 tools/audit_navigation.py`; o inventario de rotas permanece em
`AUDITORIA_ROTAS_RIO_BRANCO.csv`.

- `tests/test_individual_menu_access.py`: cobertura dos itens, bloqueio com `*`,
  liberacao isolada, URLs diretas, APIs, leitura compartilhada, persistencia e
  validacao do payload, configuracoes em lote do Zap.
- `tests/check_individual_menu_access.py`: formulario real com dados sinteticos,
  149 controles, busca, salvar/recarregar e fragmentos em desktop e celular.
- `tests/check_module_tasks.py`: telas reais e dependencias de Tecnologia com
  somente um item liberado, alem da navegacao dos tres modulos.

As verificacoes de escrita usam fixtures; nao alteram permissoes de contas reais.

## Aplicacao local — 21/09/2026

Aplicado pelo comando canonico `./up.sh`, com portal saudavel e proxies
atualizados. A verificacao HTTPS confirmou os controles existentes em Usuarios e
acessos, a correspondencia dos links do menu com o catalogo, a busca por backup
e monitoramento de link e as telas relacionadas. Os sete arquivos de codigo
conferidos no container possuem o mesmo SHA-256 do workspace.

Resultado: 83 testes unitarios aprovados; formulario verificado em desktop e
celular, bloqueio dentro do frame RioB e 54 visitas as telas dos tres modulos.
Permissoes de contas reais nao foram alteradas. Esta aplicacao e local.

## Totais de PDVs por vendedor (03/10/2026)

DADOS > RioB > Totais de PDVs por vendedor, `#vendas:pdvs_totais`, usa
`riob:vendas_pdvs` para consultar, conferir PDF e atualizar carteira. O proxy
mapeia `/api/vendas/pdvs-totais` e descendentes ao mesmo item; bloqueio individual
prevalece sobre acesso integral. O blueprint exige sessao e recurso. Percentuais
continuam em `riob:vendas`, sem conceder acesso a importacao. Nenhuma concessao
existente foi alterada. Ver `apps/riob/source/docs/PDVS_POR_VENDEDOR.md`.

Em 05/10/2026, o catalogo `riob:vendas` identifica carteira completa ou parcial.
A leitura passa a exibir a soma ja importada mesmo com cadastros ausentes;
percentuais gerais aguardam carteira completa. `riob:vendas_pdvs` continua
exclusivo da importacao. APIs, bloqueios e concessoes permanecem preservados.

## preço med.varia (07/10/2026)

O recurso `riob:vendas` identifica precos por cidade/produto e PDVs/preco medio
em popup, com ordenacao por valor ou nome. Preserva as chaves individuais e
URLs antigas, agora nomeadas `preço med.varia - Variação por cidade e produto`
e `preço med.varia - Preço médio nos PDVs e PDF`. Nenhuma concessao e alterada.

A consulta `visao=precos_cidade`, inclusive `detalhe=1`, exige a escolha do
tipo solicitado. Variacao retorna min/max, preco medio retorna medias; marcar
um nao libera o outro. Usuario somente com preco medio consulta os PDVs sem
min/max. Ordenar verifica a permissao novamente e usa dados ja carregados.
`origem=dashboard` nao autoriza esta visao; continua exclusiva da consulta
legada do dashboard. PDF conserva a permissao de preco medio. Sessao, contrato,
recurso e aliases permanecem validados no servidor. Ver ORDENACAO_PRECOS.md
na documentacao RioB e tests/test_vendas_reports_access.py.

## Vendas anual: ranking e popup (08/10/2026)

`riob:vendas` identifica o ranking anual de vendedores/clientes por perda em
hl e vendas em popup. A chave `/apps/riob#vendas:relatorio_anual` permanece,
agora nomeada Vendas Anual RioB - ranking e vendas em popup. Tipo anual e
aliases na API exigem esse item. `visao=anual_clientes`, inclusive detalhe e
paginacao, nao aceita a permissao de uma aba irma nem origem=dashboard como
alternativa. O dashboard usa origem=dashboard e seu item proprio. Nenhum
acesso e concedido automaticamente; sessao/contrato/recurso continuam validos.
Testes: tests/test_vendas_reports_access.py e check_vendas_anual.py.

## SELLOUT mensal unificado (09/10/2026)

O recurso e a concessao existentes `riob:vendas` continuam protegendo a leitura
manual em `/apps/riob#workflow:vendas_diario_importar` e a rota
`POST /api/vendas/diario/importar`. O catalogo em Config > Usuarios e acessos
agora identifica que o SELLOUT combina IND3 e INDB. Nenhum acesso novo e
concedido: sessao, contrato, item de menu e recurso continuam validados pelo
proxy, e o Render somente leitura permanece bloqueado para essa operacao.
O mesmo item exibe o status persistente da ultima tentativa em TXT, PDF, IND3 e
INDB. `GET /api/vendas/diario/status-leitura` e o POST de importacao exigem o
mesmo item individual `workflow:vendas_diario_importar`; consultar a fila nao
cria permissao separada. A limpeza posterior dos TXT/PDF processados pertence a
essa mesma rotina e nunca concede acesso novo.
