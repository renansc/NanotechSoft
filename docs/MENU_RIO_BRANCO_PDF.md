# Menu do Rio Branco conforme o PDF

Referencia de desenho: `/srv/REDE/menu.pdf`. A primeira linha define os menus; as linhas amarelas identificam o modulo de origem. As respostas do usuario prevalecem sobre a referencia.

## Decisoes confirmadas em 10/09/2026

1. Contagem separada de Acerto: conferencia em tela propria, conversao de pallets/embalagens/unidades, comparacao com o saldo consultado e exportacao CSV. O rascunho permanece apenas na pagina; exportar antes de recarregar. Atualizacao de 11/09/2026: Finalizar contagem abre conferencia e ajusta o saldo apos confirmacao, com historico, desperdicio e indicador de sobra; o recurso adicional `estoque_contagem_finalizar` e obrigatorio. Acerto continua administrativo.
2. Equipamentos e tipos reune os cadastros existentes de Motores, Drivers e Maquinas em Cadastro > Automacao. Setores permanece separado.
3. Gestao > Email tem opcoes separadas para Backup, Importar historico XML e Recuperar conteudo. Dados tambem oferece os atalhos para historico XML e backup indicados no PDF. Abrir as telas nao dispara essas acoes.
4. Gestao > XML apresenta a lista de arquivos e a revisao de abastecimentos separadamente. A revisao seleciona apenas o painel de pendencias existente; a lista de abastecimentos permanece em Estoque.
5. Relatorio > RioB > Orcamentos gerados lista os registros ja emitidos, com periodo, busca por cliente/cidade/vendedor, paginacao de 50 registros, total do filtro e acesso ao PDF salvo no sistema. Nao recalcula os orcamentos com precos atuais.

Nao restam correspondencias pendentes das cinco perguntas apresentadas.

## Acessos e contratos

O perfil `menu_profiles.rio-branco` dos manifests reorganiza os atalhos apenas neste cliente. Por solicitacao do usuario em 11/09/2026, o menu usa a ordem DASHBOARD, WORKFLOW, GESTAO, CADASTRO, RELATORIOS, DADOS, ESTOQUE, MONITOR, CONFIGURAR e DOCUMENTOS; os grupos internos identificam o modulo. Temas, Minha conta, Logo e Usuarios e acessos ficam em CONFIGURAR; Sair permanece no final do menu, antes da logo do cabecalho. Chat, IA e Telefonia permanecem no popup.

Novas concessoes em Config > Usuarios e acessos: RioB `estoque_contagem` e `vendas_orcamentos_relatorio`; Email `backup`. Email `operacao` identifica as operacoes preexistentes. Nenhuma concessao individual e adicionada automaticamente. Administradores e pessoas com `*` no modulo preservam acesso integral. As demais funcoes movidas preservam os recursos existentes. A reordenacao e os novos titulos de 11/09/2026 mantem as chaves dos grupos, URLs e recursos dos manifests: o catalogo de Usuarios e acessos e as autorizacoes no servidor continuam iguais, sem novas concessoes.

O servidor permite a `estoque_contagem` somente as dependencias de leitura `estoque/produtos` e `estoque/posicao`; nao concede ajustes. O relatorio e protegido por `vendas_orcamentos_relatorio`, que tambem permite consultar o PDF individual, sem autorizar edicao. Backup exige `backup` no modulo Email, inclusive no caminho embarcado do RioB; um usuario apenas de backup nao pode importar, recuperar ou configurar contas. Os recursos dos manifests originais permanecem no catalogo mesmo quando o perfil omite seus atalhos.

Financeiro, Ponto, Store, Cameras e ESXi ficam fora do contrato `rio-branco`, do fallback local `apps_liberados.txt` e da lista requerida desse cliente em `deploy/ecosystem.json`. URLs desses modulos sao bloqueadas ate para administrador, incluindo os caminhos embarcados de Cameras e ESXi. Codigo, dados e contratos de outros clientes sao preservados.

## Correspondencias finais

| Menu | Modulo | Funcao | Destino | Recurso |
| --- | --- | --- | --- | --- |
| GESTAO | tecnologia | Rede | `/apps/tecnologia#rede` | `rede` |
| DASHBOARD | riob | RioB - Fretes | `/apps/riob#dashboard` | `dashboard` |
| DASHBOARD | riob | Frota | `/apps/riob#dashboard:frota` | `frota` |
| DASHBOARD | riob | Estoque | `/apps/riob#dashboard:estoque` | `estoque` |
| DASHBOARD | riob | Processos operacionais | `/apps/riob#dashboard:processos` | `processos` |
| DASHBOARD | riob | Compras | `/apps/riob#dashboard:compras` | `compras` |
| DASHBOARD | riob | Vendas anual | `/apps/riob#dashboard:vendas_anual` | `vendas` |
| DASHBOARD | riob | Vendas do dia | `/apps/riob#dashboard:vendas_diario` | `vendas` |
| DASHBOARD | riob | Bonificacoes de vendas | `/apps/riob#dashboard:bonificacoes` | `vendas` |
| DASHBOARD | riob | Variacao de preco | `/apps/riob#dashboard:variacao_preco` | `vendas` |
| DASHBOARD | riob | Grupos de embalagem | `/apps/riob#dashboard:grupos_embalagem` | `vendas` |
| DASHBOARD | riob | Comissoes de vendas | `/apps/riob#dashboard:comissoes` | `comissao` |
| DASHBOARD | riob-email | Painel de e-mails | `/apps/riob-email/riob/?painel=resumo` | `operacao` |
| DASHBOARD | automacao | Dashboard Automacao | `/apps/automacao/` | `*` |
| DASHBOARD | automacao | Maquinas Automacao | `/apps/automacao/maquinas` | `*` |
| DASHBOARD | chamados | Indicadores de Chamados | `/apps/chamados?view=dashboard` | `dashboard` |
| DASHBOARD | tecnologia | Visao geral | `/apps/tecnologia#dashboard` | `dashboard` |
| DASHBOARD | tecnologia | Visao de backups | `/apps/tecnologia#backup-visao` | `backup` |
| DASHBOARD | zap | Status de entradas | `/apps/zap` | `workflow` |
| WORKFLOW | riob | Orçamento RioB | `/apps/riob#vendas:orcamento` | `vendas` |
| WORKFLOW | riob | Vendas Diario RioB | `/apps/riob#workflow:vendas_diario` | `vendas` |
| WORKFLOW | riob | Kanban RioB | `/apps/riob#fretes` | `fretes` |
| WORKFLOW | riob | Devolucoes RioB | `/apps/riob#devolucoes` | `devolucoes` |
| WORKFLOW | riob | Comissoes | `/apps/riob#comissao` | `comissao` |
| WORKFLOW | riob | Gestao de Frota RioB | `/apps/riob#gestaofrota:registrar` | `frota` |
| WORKFLOW | riob | Processos Internos RioB | `/apps/riob#processos` | `processos` |
| WORKFLOW | riob | Compras RioB | `/apps/riob#workflow:compras` | `compras` |
| WORKFLOW | automacao | Kanban Automacao | `/workflow/automacao` | `*` |
| WORKFLOW | chamados | Chamados e Manutenções | `/apps/chamados?view=chamados` | `chamados` |
| GESTAO | riob | Lista da frota | `/apps/riob#gestaofrota:lista` | `frota` |
| GESTAO | riob | Manutencoes | `/apps/riob#gestaofrota:manutencao` | `frota` |
| GESTAO | riob | Trocas de oleo | `/apps/riob#gestaofrota:oleo` | `frota` |
| GESTAO | riob | Trocas de pneus | `/apps/riob#gestaofrota:pneu` | `frota` |
| GESTAO | riob | Abastecimentos | `/apps/riob#gestaofrota:abastecimento` | `frota` |
| GESTAO | riob | Lavagens | `/apps/riob#gestaofrota:lavagem` | `frota` |
| GESTAO | riob | Previsao de compras | `/apps/riob#compras:previsao` | `compras` |
| GESTAO | riob-email | Anexos de e-mail | `/apps/riob-email/riob/anexos` | `operacao` |
| GESTAO | riob-email | E-mails | `/apps/riob-email/riob/emails` | `operacao` |
| GESTAO | riob-email | Backup de e-mails e anexos | `/apps/riob-email/riob/backup` | `backup` |
| GESTAO | riob-email | Importar historico XML | `/apps/riob-email/riob/historico` | `operacao` |
| GESTAO | riob-email | Recuperar conteudo | `/apps/riob-email/riob/recuperar` | `operacao` |
| GESTAO | riob-xml | Arquivos XML | `/apps/riob-xml/riob/arquivos` | `*` |
| GESTAO | riob-xml | Revisao de abastecimentos | `/apps/riob-xml/riob/abastecimentos?visao=revisao` | `*` |
| GESTAO | automacao | Historico | `/apps/automacao/historico` | `*` |
| GESTAO | automacao | Alarmes | `/apps/automacao/alarmes` | `*` |
| GESTAO | chamados | Agenda de Tarefas | `/apps/chamados?view=agenda` | `agenda` |
| GESTAO | zap | Agenda compartilhada | `/apps/zap/calendar` | `agenda` |
| CADASTRO | riob | Colaboradores RioB | `/apps/riob#cadastros:colaboradores` | `colaboradores` |
| CADASTRO | riob | Veiculos RioB | `/apps/riob#cadastros:veiculos` | `veiculos` |
| CADASTRO | riob | Comissoes | `/apps/riob#cadastros:comissao` | `comissao` |
| CADASTRO | riob | Cadastrar produtos RioB | `/apps/riob#cadastros:estoque_produtos` | `estoque` |
| CADASTRO | riob | Grupos de estoque RioB | `/apps/riob#cadastros:estoque_grupos` | `estoque` |
| CADASTRO | riob | Tipos de processos RioB | `/apps/riob#cadastros:processos_tipos` | `processos` |
| CADASTRO | riob | Fornecedores e compras RioB | `/apps/riob#cadastros:compras_fornecedores` | `compras` |
| CADASTRO | riob | Cargas RioB | `/apps/riob#gestaofrota:cargas` | `cargas` |
| CADASTRO | riob | Escala RioB | `/apps/riob#gestaofrota:escala` | `escala` |
| CADASTRO | riob | Pontos de venda | `/apps/riob#vendas:pontosvenda` | `pontos_venda` |
| CADASTRO | riob-email | Fornecedores | `/apps/riob-email/riob/fornecedores` | `operacao` |
| CADASTRO | automacao | Equipamentos e tipos - Motores | `/apps/automacao/motores` | `*` |
| CADASTRO | automacao | Equipamentos e tipos - Drivers | `/apps/automacao/sensores/drivers` | `*` |
| CADASTRO | automacao | Setores | `/apps/automacao/setores` | `*` |
| CADASTRO | automacao | Manual-documentacao | `/apps/automacao/documentacao/cadastrar` | `documentos_cadastrar` |
| CADASTRO | tecnologia | Equipamentos | `/apps/tecnologia#equipamentos` | `equipamentos` |
| CADASTRO | tecnologia | Planos de backup | `/apps/tecnologia#backup-planos` | `backup` |
| CADASTRO | tecnologia | Instalar agentes | `/apps/tecnologia#backup-agentes` | `backup` |
| CADASTRO | tecnologia | Descobrir impressoras | `/apps/tecnologia#descoberta-impressoras` | `equipamentos` |
| CADASTRO | tecnologia | Descobrir computadores | `/apps/tecnologia#descoberta-computadores` | `equipamentos` |
| CADASTRO | zap | Estados do fluxo | `/apps/zap/settings?secao=estados` | `settings` |
| CADASTRO | zap | Departamentos | `/apps/zap/settings?secao=departamentos` | `settings` |
| CADASTRO | zap | Etiquetas | `/apps/zap/settings?secao=etiquetas` | `settings` |
| CADASTRO | zap | Respostas rapidas | `/apps/zap/settings?secao=respostas` | `settings` |
| RELATORIOS | riob | Vendas | `/apps/riob#vendas:relatorio` | `vendas` |
| RELATORIOS | riob | Orcamentos gerados | `/apps/riob#relatorios:orcamentos` | `vendas_orcamentos_relatorio` |
| RELATORIOS | riob | Estoque comprometido | `/apps/riob#relatorios:estoque_comprometido` | `estoque` |
| RELATORIOS | riob | Processos operacionais | `/apps/riob#relatorios:processos` | `processos` |
| RELATORIOS | riob | Comissoes | `/apps/riob#comissao:relatorios` | `comissao` |
| RELATORIOS | riob | Frota | `/apps/riob#gestaofrota:relatorios` | `frota` |
| RELATORIOS | riob | Contagens, desperdicio e sobras | `/apps/riob#relatorios:contagens` | `estoque_contagem_relatorio` |
| RELATORIOS | riob | Compras RioB | `/apps/riob#relatorios:compras` | `compras` |
| RELATORIOS | riob | Vendas Anual RioB | `/apps/riob#vendas:relatorio_anual` | `vendas` |
| RELATORIOS | riob | Visitas dos pontos de venda | `/apps/riob#vendas:pontosvenda_relatorio` | `pontos_venda` |
| RELATORIOS | riob | Cargas da semana | `/apps/riob#relatorios:cargas_semana` | `vendas` |
| RELATORIOS | riob | Variacao de preco | `/apps/riob#vendas:variacao_preco` | `vendas` |
| RELATORIOS | riob | Grupos de embalagem | `/apps/riob#vendas:grupos_embalagem` | `vendas` |
| RELATORIOS | riob | Preco medio | `/apps/riob#vendas:preco_medio` | `vendas` |
| RELATORIOS | chamados | Histórico de Soluções | `/apps/chamados?view=historico` | `historico` |
| RELATORIOS | tecnologia | Historico | `/apps/tecnologia#historico` | `historico` |
| RELATORIOS | tecnologia | Ocupacao do link | `/apps/tecnologia#ocupacao-link` | `historico` |
| DADOS | riob | Vendas do dia | `/apps/riob#workflow:vendas_diario_importar` | `vendas` |
| DADOS | riob | Comissoes | `/apps/riob#comissao:exportar` | `comissao` |
| DADOS | riob | E-mails | `/apps/riob#monitor:gestor_emails` | `gestor-emails` |
| DADOS | riob | Importar XML (Bipe) RioB | `/apps/riob#estoque:importar_xml_bipe` | `estoque` |
| DADOS | riob | Importar XML Auto RioB | `/apps/riob#estoque:importar_xml_auto` | `estoque` |
| DADOS | riob | Importar pontos de venda | `/apps/riob#vendas:pontosvenda_importar` | `pontos_venda` |
| DADOS | riob | Base mensal de vendas | `/apps/riob#config:base_vendas` | `config` |
| DADOS | riob-email | XML - Importar historico | `/apps/riob-email/riob/historico` | `operacao` |
| DADOS | riob-email | Backup de e-mails | `/apps/riob-email/riob/backup` | `backup` |
| DADOS | riob-email | Importar e-mails | `/apps/riob-email/riob/importacao` | `operacao` |
| DADOS | riob-xml | Importar XML | `/apps/riob-xml/riob` | `*` |
| ESTOQUE | riob | Posicao | `/apps/riob#estoque:posicao` | `estoque` |
| ESTOQUE | riob | Movimentar | `/apps/riob#estoque:movimentar` | `estoque` |
| ESTOQUE | riob | Rastreio | `/apps/riob#estoque:rastreio` | `estoque` |
| ESTOQUE | riob | Acerto | `/apps/riob#estoque:acerto` | `estoque` |
| ESTOQUE | riob | Contagem | `/apps/riob#estoque:contagem` | `estoque_contagem` |
| ESTOQUE | riob-xml | Estoque de XMLs recebidos | `/apps/riob-xml/riob/estoque` | `*` |
| ESTOQUE | riob-xml | Abastecimentos de XMLs recebidos | `/apps/riob-xml/riob/abastecimentos` | `*` |
| MONITOR | riob | Monitor Automacao RioB | `/apps/riob#monitor:automacao` | `automacao` |
| MONITOR | riob-email | Status de e-mails | `/apps/riob-email/riob/?painel=status` | `operacao` |
| MONITOR | automacao | Tempo real | `/apps/automacao/tempo-real` | `*` |
| MONITOR | zap | Status das integracoes | `/apps/zap/settings?secao=status` | `settings` |
| CONFIGURAR | riob | Backup do RioB | `/apps/riob#config:backup` | `config` |
| CONFIGURAR | riob | NF-e / Receita | `/apps/riob#config:nfe` | `config` |
| CONFIGURAR | riob | Parametros de orcamentos | `/apps/riob#config:orcamentos` | `config` |
| CONFIGURAR | riob-email | Contas de e-mail | `/apps/riob-email/riob/config` | `operacao` |
| CONFIGURAR | riob-xml | Configuracao da empresa | `/apps/riob-xml/riob/config` | `*` |
| CONFIGURAR | tecnologia | Configuracao | `/apps/tecnologia#config` | `config` |
| CONFIGURAR | zap | Webhook WhatsApp | `/apps/zap/settings?secao=webhook` | `settings` |
| CONFIGURAR | zap | WhatsApp Business | `/apps/zap/settings?secao=whatsapp` | `settings` |
| CONFIGURAR | zap | Backup AlwaysData | `/apps/zap/settings?secao=backup` | `settings` |
| CONFIGURAR | zap | Configurar agenda | `/apps/zap/settings?secao=agenda` | `settings` |
| CONFIGURAR | zap | Lembretes | `/apps/zap/settings?secao=lembretes` | `settings` |
| CONFIGURAR | zap | Integracoes extras | `/apps/zap/settings?secao=integracoes` | `settings` |
| CONFIGURAR | zap | Usuarios do Zap | `/apps/zap/settings?secao=usuarios` | `settings` |
| CONFIGURAR | zap | Configuracao atual | `/apps/zap/settings?secao=valores` | `settings` |
| DOCUMENTOS | automacao | Manuais das maquinas | `/apps/automacao/documentacao` | `documentos` |
| DOCUMENTOS | chamados | Manuais e Documentações | `/apps/chamados?view=documentos` | `documentos` |
| DOCUMENTOS | tecnologia | Agentes e protocolos | `/apps/tecnologia#protocolos` | `equipamentos` |
| DOCUMENTOS | zap | Guia do Gestor | `/apps/zap/docs` | `docs` |

## Implementacao e verificacao

O carregador `normalize_app` preserva `menu_profiles` ao ler os manifests.
Menu e catalogo de permissoes recebem esse perfil pelo fluxo real
`filesystem_apps -> list_apps`; os testes cobrem esse carregamento completo.

As paginas HTML em `/apps/` usam `Cache-Control: no-store, no-cache, must-revalidate`.
Os links do shell para `static/app.js` e `static/style.css` incluem uma versao
derivada do conteudo, para que uma atualizacao carregue a navegacao e o estilo
novos tambem no celular. Essa politica nao cria recursos nem altera o catalogo
ou as autorizacoes existentes.

Tecnologia usa `#backup-visao`, `#backup-planos` e `#backup-agentes` para selecionar paineis existentes. Email usa `?painel=resumo` e `?painel=status` para mostrar somente o painel escolhido.

O backup ZIP e uma exportacao dos e-mails importados e anexos locais: mensagens e metadados em JSON Lines por lote, anexos organizados por ID, marcacao de anexos indisponiveis. Nao inclui senhas/configuracoes das contas, nao acessa POP3/IMAP, nao restaura dados e nao substitui o backup do banco. Usa arquivo temporario e leitura paginada para evitar acumular o arquivo completo em memoria.

Testes: `tests/test_menu_pdf.py`, `tests/check_menu_pdf.py`, `apps/riob/source/tests/test_menu_relatorios.py`, suites existentes de navegacao, acessos, comunicacao e contratos. Fixtures de navegador e backup usam somente dados sinteticos.

## Auditoria de preservacao dos atalhos (14/09/2026)

Os atalhos XML em `/apps/riob-xml/riob/...` sao encaminhados ao blueprint
integrado `/importar-xml/...`, incluindo estoque e abastecimentos. Em
14/09/2026 foi corrigida a perda desse prefixo nas subpaginas, que causava 404.
Links internos preservam o modulo XML e o recurso existente `riob-xml:*`.
Os testes de proxy verificam tambem as rotas reais, alem da presenca no menu.

A substituicao integral por `menu_profiles.rio-branco` omitiu destinos que
existiam no manifest base. A verificacao anterior preservava o catalogo de
recursos, mas nao comparava todos os URLs do menu. Nao houve remocao dos PDFs:
Documentos > Automacao > Manuais das maquinas volta a abrir a listagem existente,
com guias e arquivos da Rodighero ER-1500 e Zegla Unimix 20.000 L. Os manuais de
Chamados passam de Cadastro para Documentos, mantendo o recurso `documentos`.

A revisao dos arquivos de origem localizou tambem o PDF da Envasadora Zegla
40/50/10 GA em `ProjetoEnchedora`. Esse terceiro documento foi incorporado ao
mesmo catalogo, com slug e PDF proprios, preservando o manual da Brix. A capa
identifica RZ-RET-G-40/50/10-GA-GII, confirmado pela operacao em 14/09/2026.

Tambem foram recuperados Workflow do RioB (Orcamentos, Vendas Diario, Fretes,
Devolucoes, Comissoes, Frota, Processos e Compras), Kanban Automacao, relatorios
Compras/Vendas Anual, importacoes XML, configuracoes SIP/Vendas,
Monitor Automacao e Configuracoes Zap. As URLs e os recursos anteriores foram
preservados; nenhuma permissao foi concedida automaticamente.

`test_existing_destinations_are_preserved_by_client_menu` verifica todos os
menus, configuracoes e cards dos manifests dos apps contratados contra os links
efetivamente publicados pelo menu. Um destino novo omitido faz o teste falhar.
As unicas equivalencias sem repetir links sao:

- Tecnologia raiz -> `#dashboard`;
- Tecnologia `#backup` -> `#backup-visao`, `#backup-planos` e `#backup-agentes`;
- Gestor de e-mails raiz -> `?painel=resumo`.

As exclusoes intencionais continuam sendo Cameras e ESXi (contrato desativado),
Chat, IA, Agent IA e Telefonia (popup de Comunicacao, conforme decisao anterior).
O teste nao aceita outras omissoes sem revisao explicita. A verificacao de
Documentos cobre menu autorizado/restrito, login, guias, PDFs e reescrita dos
links no portal. Os demais clientes mantem os respectivos manifests base.

## Auditoria de telas e funcoes

A revisao de 14/09/2026 tambem verifica rotas e separacao de tarefas, alem da
presenca dos atalhos. A matriz acima incorpora as correcoes dessa revisao.
Consulte [Auditoria de navegacao](AUDITORIA_NAVEGACAO_RIO_BRANCO.md).

## Cabecalho e paginas completas (15/09/2026)

XML e Email passam a usar o cabecalho e o menu principal do portal com a tarefa
isolada. Estoque de XMLs recebidos nao mostra o menu interno do importador.
Filtros e links preservam o destino; downloads e previews continuam contextuais.
O nome do deploy, usuario e Sair nao mudam ao trocar de funcao.
O atalho de modo completo foi substituido por Documentacao RioB em DOCUMENTOS
(`riob:config`). `/apps/riob/original` permanece como redirecionamento compativel
para `/apps/riob`. O catalogo usa os manifests sem ampliar acessos existentes.

| DOCUMENTOS | riob | Documentacao RioB | `/apps/riob/docs/` | `config` |

## Correcao de omissoes em Tecnologia (16/09/2026)

Os atalhos abaixo tornam explicitos o monitoramento e a configuracao dos backups.
As entradas anteriores de Dashboard/Cadastro permanecem validas; cada destino
seleciona apenas sua tarefa. O consumo atual do link sai do formulario de
configuracao e ganha tela de monitoramento. Nao ha novas concessoes.

| Menu | Modulo | Funcao | Destino | Recurso |
| --- | --- | --- | --- | --- |
| MONITOR | tecnologia | Monitoramento de link | `/apps/tecnologia#monitor-link` | `dashboard` |
| MONITOR | tecnologia | Monitoramento de backups | `/apps/tecnologia#backup-visao` | `backup` |
| CONFIGURAR | tecnologia | Planos de backup | `/apps/tecnologia#backup-planos` | `backup` |
| CONFIGURAR | tecnologia | Instalar agentes de backup | `/apps/tecnologia#backup-agentes` | `backup` |

A cobertura dos tres modulos usa agora as telas de origem, alem dos manifests:
Tecnologia e Chamados pelos `data-page`, Automacao pelos links originais.
APIs de Tecnologia conferem os recursos existentes tambem em acesso direto;
usuario apenas de backup nao recebe dados de rede. Abrir Historico diretamente
aguarda os equipamentos para carregar suas medicoes. Detalhes em
[Auditoria dos tres modulos](AUDITORIA_TRES_MODULOS.md).

## Custo do produto (21/09/2026)

GESTAO > RioB > Custo do produto abre `/apps/riob#custoProduto` com recurso
`riob:custo_produto`. O atalho tambem consta do manifest base e do catalogo
Config > Usuarios e acessos. GET/PUT `/apps/riob/api/custo-produto` (PUT com
ID do produto) exigem a autorizacao correspondente, respeitando bloqueios
individuais. Nenhuma permissao existente e ampliada. Detalhes em
[Custo do produto](../apps/riob/source/docs/CUSTO_PRODUTO.md).

Em 22/09/2026, DASHBOARD > RioB > Custo do produto ganhou o destino
`/apps/riob#custoProdutoDashboard`, com recurso `riob:custo_produto_dashboard`.
A consulta atual/mensal possui autorizacao independente da edicao, no manifest
base, perfil Rio Branco, catalogo de usuarios, proxy e API. O custo usa a ultima
NF-e de fornecedor; a comparacao mensal reprecifica a formula atual ate cada
mes, sem representar receitas historicas. GESTAO mantem cadastro de xarope e
doses diferentes por produto com `custo_produto`. Nenhuma permissao e ampliada.

Custo do produto reaproveita os vinculos confirmados entre XML e estoque para
resolver ingredientes renomeados e consultar o ultimo valor sem exigir pedido
em Compras. Codigo/fornecedor ou codigo/descricao historica devem identificar
um unico produto. Acucar em venda a ordem entra na referencia; TO/tonelada
converte para kg e capacidade de saco ja cadastrada e reutilizada quando a
apresentacao confirmada corresponde. O catalogo identifica o recurso existente
`custo_produto` como Custo do produto, xarope e precos do XML; dashboard conserva
`custo_produto_dashboard`. APIs e bloqueios individuais mantem a autorizacao,
sem novas concessoes. Detalhes e limites no documento CUSTO_PRODUTO.md do RioB.

Em 23/09/2026, GESTAO > Custos diarios por grupo (`#custoDiario`, recurso
`custo_diario`) passa a informar producao real, pessoal e despesas por grupo.
Dashboard de custo do produto mantem o recurso `custo_produto_dashboard` e
oferece custo diario por litro, garrafa e pacote, alem da comparacao mensal.
Gastos compartilhados sao rateados pelos litros. Desperdicio vem exclusivamente
das faltas em contagens finalizadas, agrupadas por setor/grupo de estoque;
perdas especificas de producao ficam para uma etapa futura. As APIs
`/api/custo-diario` (GET/PUT) e `/api/custo-diario/dashboard` (GET) validam sessao,
recursos e bloqueios individuais; nao concedem acesso nem movimentam estoque.
Regras, snapshots e limites em `apps/riob/source/docs/CUSTO_DIARIO.md` na raiz.
