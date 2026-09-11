# Menu do Rio Branco conforme o PDF

Referencia de desenho: `/srv/REDE/menu.pdf`. A primeira linha define os menus; as linhas amarelas identificam o modulo de origem. As respostas do usuario prevalecem sobre a referencia.

## Decisoes confirmadas em 10/09/2026

1. Contagem separada de Acerto: conferencia em tela propria, conversao de pallets/embalagens/unidades, comparacao com o saldo consultado e exportacao CSV. O rascunho permanece apenas na pagina; exportar antes de recarregar. Nao altera saldos. Acerto continua administrativo e registra a diferenca no historico.
2. Equipamentos e tipos reune os cadastros existentes de Motores, Drivers e Maquinas em Cadastro > Automacao. Setores permanece separado.
3. Gestao > Email tem opcoes separadas para Backup, Importar historico XML e Recuperar conteudo. Dados tambem oferece os atalhos para historico XML e backup indicados no PDF. Abrir as telas nao dispara essas acoes.
4. Gestao > XML apresenta a lista de arquivos e a revisao de abastecimentos separadamente. A revisao seleciona apenas o painel de pendencias existente; a lista de abastecimentos permanece em Estoque.
5. Relatorio > RioB > Orcamentos gerados lista os registros ja emitidos, com periodo, busca por cliente/cidade/vendedor, paginacao de 50 registros, total do filtro e acesso ao PDF salvo no sistema. Nao recalcula os orcamentos com precos atuais.

Nao restam correspondencias pendentes das cinco perguntas apresentadas.

## Acessos e contratos

O perfil `menu_profiles.rio-branco` dos manifests reorganiza os atalhos apenas neste cliente. O menu usa a ordem Dash, Cadastro, Relatorio, Dados, Config, Workflow, Monitor, Estoque, Gestao e Docs; os grupos internos identificam o modulo. Temas, Minha conta e Usuarios e acessos ficam em Config; Sair permanece na direita do cabecalho. Chat, IA e Telefonia permanecem no popup.

Novas concessoes em Config > Usuarios e acessos: RioB `estoque_contagem` e `vendas_orcamentos_relatorio`; Email `backup`. Email `operacao` identifica as operacoes preexistentes. Nenhuma concessao individual e adicionada automaticamente. Administradores e pessoas com `*` no modulo preservam acesso integral. As demais funcoes movidas preservam os recursos existentes.

O servidor permite a `estoque_contagem` somente as dependencias de leitura `estoque/produtos` e `estoque/posicao`; nao concede ajustes. O relatorio e protegido por `vendas_orcamentos_relatorio`, que tambem permite consultar o PDF individual, sem autorizar edicao. Backup exige `backup` no modulo Email, inclusive no caminho embarcado do RioB; um usuario apenas de backup nao pode importar, recuperar ou configurar contas. Os recursos dos manifests originais permanecem no catalogo mesmo quando o perfil omite seus atalhos.

Financeiro, Ponto, Store, Cameras e ESXi ficam fora do contrato `rio-branco`, do fallback local `apps_liberados.txt` e da lista requerida desse cliente em `deploy/ecosystem.json`. URLs desses modulos sao bloqueadas ate para administrador, incluindo os caminhos embarcados de Cameras e ESXi. Codigo, dados e contratos de outros clientes sao preservados.

## Correspondencias finais

| Menu | Modulo | Funcao | Destino | Recurso |
| --- | --- | --- | --- | --- |
| Dash | riob | RioB - Fretes | `/apps/riob#dashboard` | `dashboard` |
| Dash | riob | Frota | `/apps/riob#dashboard:frota` | `frota` |
| Dash | riob | Estoque | `/apps/riob#dashboard:estoque` | `estoque` |
| Dash | riob | Processos operacionais | `/apps/riob#dashboard:processos` | `processos` |
| Dash | riob | Compras | `/apps/riob#dashboard:compras` | `compras` |
| Dash | riob | Vendas anual | `/apps/riob#dashboard:vendas_anual` | `vendas` |
| Dash | riob | Vendas do dia | `/apps/riob#dashboard:vendas_diario` | `vendas` |
| Dash | riob | Bonificacoes de vendas | `/apps/riob#dashboard:bonificacoes` | `vendas` |
| Dash | riob | Variacao de preco | `/apps/riob#dashboard:variacao_preco` | `vendas` |
| Dash | riob | Grupos de embalagem | `/apps/riob#dashboard:grupos_embalagem` | `vendas` |
| Dash | riob | Comissoes de vendas | `/apps/riob#dashboard:comissoes` | `comissao` |
| Dash | riob-email | Painel de e-mails | `/apps/riob-email/riob/?painel=resumo` | `operacao` |
| Dash | automacao | Dashboard Automacao | `/apps/automacao/` | `*` |
| Dash | automacao | Maquinas Automacao | `/apps/automacao/maquinas` | `*` |
| Dash | chamados | Indicadores de Chamados | `/apps/chamados?view=dashboard` | `dashboard` |
| Dash | tecnologia | Visao geral | `/apps/tecnologia#dashboard` | `dashboard` |
| Dash | tecnologia | Visao de backups | `/apps/tecnologia#backup-visao` | `backup` |
| Dash | zap | Status de entradas | `/apps/zap` | `workflow` |
| Cadastro | riob | Colaboradores RioB | `/apps/riob#cadastros:colaboradores` | `colaboradores` |
| Cadastro | riob | Veiculos RioB | `/apps/riob#cadastros:veiculos` | `veiculos` |
| Cadastro | riob | Comissoes | `/apps/riob#cadastros:comissao` | `comissao` |
| Cadastro | riob | Cadastrar produtos RioB | `/apps/riob#cadastros:estoque_produtos` | `estoque` |
| Cadastro | riob | Grupos de estoque RioB | `/apps/riob#cadastros:estoque_grupos` | `estoque` |
| Cadastro | riob | Tipos de processos RioB | `/apps/riob#cadastros:processos_tipos` | `processos` |
| Cadastro | riob | Fornecedores e compras RioB | `/apps/riob#cadastros:compras_fornecedores` | `compras` |
| Cadastro | riob | Cargas RioB | `/apps/riob#gestaofrota:cargas` | `cargas` |
| Cadastro | riob | Escala RioB | `/apps/riob#gestaofrota:escala` | `escala` |
| Cadastro | riob-email | Painel de e-mails | `/apps/riob-email/riob/?painel=resumo` | `operacao` |
| Cadastro | riob-email | Contas de e-mail | `/apps/riob-email/riob/config` | `operacao` |
| Cadastro | riob-email | Fornecedores | `/apps/riob-email/riob/fornecedores` | `operacao` |
| Cadastro | riob-xml | Configuracao da empresa | `/apps/riob-xml/riob/config` | `*` |
| Cadastro | automacao | Equipamentos e tipos - Motores | `/apps/automacao/motores` | `*` |
| Cadastro | automacao | Equipamentos e tipos - Drivers | `/apps/automacao/sensores/drivers` | `*` |
| Cadastro | automacao | Equipamentos e tipos - Maquinas | `/apps/automacao/maquinas` | `*` |
| Cadastro | automacao | Setores | `/apps/automacao/setores` | `*` |
| Cadastro | chamados | Manuais e Documentações | `/apps/chamados?view=documentos` | `documentos` |
| Cadastro | tecnologia | Equipamentos | `/apps/tecnologia#equipamentos` | `equipamentos` |
| Cadastro | tecnologia | Planos de backup | `/apps/tecnologia#backup-planos` | `backup` |
| Cadastro | tecnologia | Instalar agentes | `/apps/tecnologia#backup-agentes` | `backup` |
| Cadastro | tecnologia | Configuracao | `/apps/tecnologia#config` | `config` |
| Cadastro | zap | Google Agenda | `/apps/zap/calendar` | `agenda` |
| Relatorio | riob | Vendas | `/apps/riob#vendas:relatorio` | `vendas` |
| Relatorio | riob | Orcamentos gerados | `/apps/riob#relatorios:orcamentos` | `vendas_orcamentos_relatorio` |
| Relatorio | riob | Estoque comprometido | `/apps/riob#relatorios:estoque_comprometido` | `estoque` |
| Relatorio | riob | Processos operacionais | `/apps/riob#relatorios:processos` | `processos` |
| Relatorio | riob | Comissoes | `/apps/riob#comissao:relatorios` | `comissao` |
| Relatorio | riob | Frota | `/apps/riob#gestaofrota:relatorios` | `frota` |
| Relatorio | chamados | Histórico de Soluções | `/apps/chamados?view=historico` | `historico` |
| Relatorio | tecnologia | Historico | `/apps/tecnologia#historico` | `historico` |
| Dados | riob | Vendas do dia | `/apps/riob#workflow:vendas_diario_importar` | `vendas` |
| Dados | riob | Comissoes | `/apps/riob#comissao:exportar` | `comissao` |
| Dados | riob | E-mails | `/apps/riob#monitor:gestor_emails` | `gestor-emails` |
| Dados | riob | NF-e / Receita | `/apps/riob#config:nfe` | `config` |
| Dados | riob-email | XML - Importar historico | `/apps/riob-email/riob/historico` | `operacao` |
| Dados | riob-email | Backup de e-mails | `/apps/riob-email/riob/backup` | `backup` |
| Config | riob | Logs | `/apps/riob#config:logs` | `config` |
| Config | riob | Status | `/apps/riob#config:status` | `config` |
| Workflow | chamados | Chamados e Manutenções | `/apps/chamados?view=chamados` | `chamados` |
| Monitor | riob-email | Status de e-mails | `/apps/riob-email/riob/?painel=status` | `operacao` |
| Monitor | automacao | Tempo real | `/apps/automacao/tempo-real` | `*` |
| Estoque | riob | Previsao de compras | `/apps/riob#compras:previsao` | `compras` |
| Estoque | riob | Posicao | `/apps/riob#estoque:posicao` | `estoque` |
| Estoque | riob | Movimentar | `/apps/riob#estoque:movimentar` | `estoque` |
| Estoque | riob | Rastreio | `/apps/riob#estoque:rastreio` | `estoque` |
| Estoque | riob | Acerto | `/apps/riob#estoque:acerto` | `estoque` |
| Estoque | riob | Contagem | `/apps/riob#estoque:contagem` | `estoque_contagem` |
| Estoque | riob-xml | Estoque de XMLs recebidos | `/apps/riob-xml/riob/estoque` | `*` |
| Estoque | riob-xml | Abastecimentos de XMLs recebidos | `/apps/riob-xml/riob/abastecimentos` | `*` |
| Gestao | riob-email | Anexos de e-mail | `/apps/riob-email/riob/anexos` | `operacao` |
| Gestao | riob-email | E-mails | `/apps/riob-email/riob/emails` | `operacao` |
| Gestao | riob-email | Backup de e-mails e anexos | `/apps/riob-email/riob/backup` | `backup` |
| Gestao | riob-email | Importar historico XML | `/apps/riob-email/riob/historico` | `operacao` |
| Gestao | riob-email | Recuperar conteudo | `/apps/riob-email/riob/recuperar` | `operacao` |
| Gestao | riob-xml | Arquivos XML | `/apps/riob-xml/riob/arquivos` | `*` |
| Gestao | riob-xml | Revisao de abastecimentos | `/apps/riob-xml/riob/abastecimentos?visao=revisao` | `*` |
| Gestao | automacao | Historico | `/apps/automacao/historico` | `*` |
| Gestao | automacao | Alarmes | `/apps/automacao/alarmes` | `*` |
| Gestao | chamados | Agenda de Tarefas | `/apps/chamados?view=agenda` | `agenda` |
| Gestao | tecnologia | Serie temporal | `/apps/tecnologia#historico` | `historico` |
| Gestao | tecnologia | Ocupacao do link | `/apps/tecnologia#ocupacao-link` | `historico` |
| Docs | tecnologia | Agentes e protocolos | `/apps/tecnologia#protocolos` | `equipamentos` |
| Docs | zap | Guia do Gestor | `/apps/zap/docs` | `docs` |

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
