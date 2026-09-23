# Auditoria de navegacao do Rio Branco — 14/09/2026

Atualizacao de acessos: os destinos agora possuem controles individuais em
Configurar > Usuarios e acessos. Veja o [mapa de 137 itens](MAPA_ACESSOS_MENU.csv)
e as [regras de bloqueio e liberacao](ACESSOS_POR_ITEM_MENU.md). Os numeros abaixo
registram a auditoria original; o CSV de rotas e regenerado pelo inventario atual.

Escopo: perfil local Rio Branco, com RioB, XML, Email, Automacao, Chamados,
Tecnologia, Zap e a navegacao compartilhada do portal. A ordem das dez categorias
principais permanece a solicitada pelo usuario.

## Inventario e criterio

- 132 atalhos nos manifests dos sete aplicativos, alem das opcoes comuns de Configurar.
- 443 declaracoes de rotas nos controladores do portal e dos aplicativos ativos:
  342 associadas a telas, 11 a acoes contextuais, 42 de infraestrutura,
  5 de integracao e 43 de modulos fora do contrato deste cliente.
- 461 eventos de interface no HTML principal do RioB chamam 267 funcoes distintas;
  todas possuem implementacao nos scripts do aplicativo.
- 70 destinos do RioB exercitados no navegador em 140 transicoes, nos dois sentidos.

[Inventario por rota e funcao](AUDITORIA_ROTAS_RIO_BRANCO.csv) registra arquivo,
linha, metodo, rota, classificacao e acesso associado. Gerar novamente com
`python3 tools/audit_navigation.py`. [Matriz de menus](MENU_RIO_BRANCO_PDF.md)
registra os atalhos e seus recursos de acesso.

Uma pagina operacional possui menu/submenu. Acoes como salvar, excluir, abrir
PDF, editar um registro ou consultar seu historico permanecem ligadas ao botao
ou popup da tela correspondente. APIs, arquivos estaticos, sessao, callbacks e
recebimento de telemetria nao viram itens de menu. Funcoes auxiliares internas
sao implementacao dessas tarefas. O inventario e estatico: associacao a uma
funcao nao significa que cada operacao de escrita tenha sido executada.

## Correcoes

- Cadastro e relatorio de Pontos de Venda recuperados; importacao CSV ganhou
  tarefa propria em Dados, separada do formulario de cadastro.
- Lista da frota e atalhos diretos de manutencao, oleo, pneus, abastecimento e
  lavagem incluidos em Gestao, usando os paineis existentes.
- Relatorios de variacao de preco, grupos de embalagem e preco medio receberam
  atalhos diretos. Abrir Vendas/Relatorio volta para Bonificacoes; a tela nao
  herda o ultimo relatorio anual escolhido.
- Cargas da semana saiu do corpo do Kanban e abre em Relatorios. O botao do
  Kanban encaminha para essa mesma tela.
- Backup do RioB saiu de Status. Parametros de orcamentos e base mensal de
  vendas foram separados da configuracao da integracao de vendas.
- Comissoes volta aos lancamentos quando aberta pelo menu operacional, mesmo
  depois de consultar relatorio ou exportacao.
- Configuracoes de Tecnologia, contas de Email, empresa XML e NF-e ficaram em
  Configurar. Ocupacao do link ficou em Relatorios; previsao de compras em
  Gestao; agenda compartilhada do Zap em Gestao.
- Removidos atalhos duplicados de painel de Email, historico de Tecnologia e
  maquinas monitoradas de Automacao que apareciam como se fossem cadastros.
- Descoberta de impressoras e computadores agora tem duas telas especificas;
  a lista de equipamentos conserva somente sua tarefa de cadastro.
- Zap mostra uma tarefa de configuracao por pagina (`settings?secao=...`), com
  submenus para estados, departamentos, etiquetas, respostas, WhatsApp, webhook,
  agenda, lembretes, integracoes, status, usuarios, backup e valores atuais.
- Subpaginas de Email corrigidas para o blueprint `/gestor-emails/`, assim como
  XML usa `/importar-xml/`. Links, formularios e redirecionamentos preservam o
  modulo autorizado. Importar e-mails tem pagina propria em Dados; o painel
  inicial exibe somente Resumo.

## Acessos

Os manifests alimentam Configurar > Usuarios e acessos. `pontos_venda`, antes
sem atalho no manifest, passa a aparecer para liberacao explicita; nenhuma
concessao individual e criada. Os demais atalhos reutilizam `frota`, `vendas`,
`config`, `equipamentos`, `operacao` e `settings`, conforme sua tarefa.

O servidor valida os recursos do Zap tambem para URLs digitadas diretamente.
As rotas de Processos e dashboards de Processos/Compras usam os nomes de recurso
ja publicados; configuracao NF-e usa `config`. Os bloqueios por contrato,
usuario sem permissao e sessao ausente continuam cobertos. As operacoes
administrativas mantem suas verificacoes internas existentes.

## Verificacao

- `tests/test_navigation_audit.py`: associacoes, rotas reais dos blueprints,
  vistas estaticas, paginas separadas do Zap e permissoes.
- `tests/check_navigation_audit.py`: navega por todos os hashes do manifest RioB,
  verifica o destino escolhido e exige uma unica tarefa visivel por familia.
- `tests/test_riob_xml_proxy.py`: paginas reais de XML e Email, filtros,
  exportacao CSV, formularios e preservacao dos prefixos autenticados.
- Suites existentes de menu, permissoes e navegador continuam aplicaveis.

Fixtures usam dados sinteticos e nao executam importacoes, envios, restauracoes
ou alteracoes de estoque. A verificacao local apos `./up.sh` consulta somente
paginas e servicos. Esta auditoria nao publica outra revisao no GitHub/Render.

## Situacao da aplicacao local em 14/09/2026

A tentativa de aplicar pelo comando canonico `./up.sh` foi bloqueada na
verificacao das pastas, antes de reconstruir/reiniciar os aplicativos. A montagem
`//192.168.200.121/d` em `/media/serverwin` falhou com `Host is down`; a conexao
TCP ao SMB/445 retornou `No route to host`. Log da tentativa:
`/tmp/nanotech-auditoria-navegacao-up.log`.

As correcoes estao no workspace e os testes passaram; a versao em execucao ainda
e a anterior a esta auditoria. Quando o compartilhamento voltar, aplicar com
`./up.sh` na raiz e conferir as paginas no servico atualizado. Nenhuma pasta
vazia foi criada para substituir as fontes, nem bancos foram restaurados.

## Correcao do shell e identidade (15/09/2026)

- XML/Email conservam o menu principal em todas as paginas de tarefa, incluindo
  filtros GET e formularios POST. A pagina antiga fornece somente o conteudo;
  seus estilos ficam isolados no frame e seus menus internos sao removidos.
- Formularios sem action recebem o endereco da tarefa. Links/formularios usam
  o portal como destino, evitando shells aninhados. URLs relativas a origem
  conservam HTTPS quando o portal esta atras do proxy.
- Nome do contrato do deploy, usuario, marca e Sair permanecem no cabecalho em
  Config, RioB e demais apps. O menu compacto nao esconde Sair.
- Configurar separa Minha conta, Temas, Logo, Usuarios, Clientes e Backup. As
  autorizacoes existentes continuam: perfil admin nas tres ultimas e
  `sistema:logo` na logo. Nenhuma concessao e alterada.
- Documentacao RioB substitui o atalho Modo completo e exige `riob:config` no
  manifest/catalogo e servidor. `/apps/riob/original` redireciona para o shell.
- `tests/check_integrated_shell.py` verifica estoque, filtro, menu Email e Minha
  conta em 1440, 390 e 320 pixels, sem escritas de negocio.
- Inventario regenerado: 443 rotas, 132 atalhos, 267 funcoes dos eventos HTML;
  nenhuma rota sem associacao e nenhuma funcao de evento ausente.

### Validacao local em 15/09/2026

`./up.sh` concluiu a reconstrucao de portal/RioB e a verificacao dos proxies.
Log: `/tmp/nanotech-shell-final-up.log`. HTTPS `/healthz` retornou 200. Consultas
autenticadas de leitura nas paginas RioB, estoque XML, Email, Config e Docs
retornaram 200, um unico menu principal, Rio Branco e Sair no cabecalho.
Os SHA-256 de app.py, JavaScript, CSS e templates principais no container
coincidiram com o workspace. Bancos nao foram restaurados nem sincronizados.

Testes de navegador passaram com usuario comum e administrador; Minha conta,
Temas, Logo, Usuarios, Clientes e Backup exibem somente os paineis da tarefa.
As alteracoes permanecem locais, sem commit/push desta revisao ou publicacao
no Render. O HEAD/origin/main consultado continua c395407.

## Telas por tarefa no portal (15/09/2026)

Os atalhos abrem somente a tarefa selecionada, com o cabecalho e o menu
principal do deploy. As entradas antigas `/original` redirecionam para a URL
integrada, preservando caminho, filtros e metodo HTTP. O manifest usa a entrada
integrada tambem em `standalone_url`. Nao existe segundo menu de aplicativo.

Tecnologia concentra Verificar agora/Testar velocidade na Visao geral, alertas
de e-mail em Configuracao e explicacoes de escopo em Agentes e protocolos.
Chamados exibe Novo chamado somente na fila; Agenda, Historico e Documentos
mostram suas proprias tarefas, inclusive antes do carregamento dos dados.
Automacao extrai o conteudo entre marcadores do template e aplica seus estilos
somente dentro da tarefa, preservando os botoes e a identidade do portal.

Os mesmos recursos continuam em Usuarios e acessos: Tecnologia usa dashboard,
equipamentos, historico, config e backup; Chamados usa dashboard, chamados,
agenda, historico e documentos; Automacao explicita o recurso existente `*`.
Nenhuma concessao e criada. Sessao, contrato e bloqueios do servidor continuam
valendo tambem nos aliases. Testes: `tests/test_module_tasks.py` e
`tests/check_module_tasks.py`, com dados sinteticos e sem escritas de negocio.
