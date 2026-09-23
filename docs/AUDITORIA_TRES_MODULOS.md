# Auditoria de Tecnologia, Automacao e Chamados — 16/09/2026

## Problema encontrado

A auditoria anterior usava os destinos dos manifests como referencia. Isso nao
detectava telas ausentes do proprio manifest nem garantia a distribuicao em
Monitor/Configurar. Tecnologia nao tinha grupo em MONITOR; consumo atual do
link estava no formulario de Configuracao, e planos/agentes de backup ficavam
apenas em Cadastro. O manifest base tambem omitia Agentes e protocolos e nao
dava entrada direta para Alarmes da Automacao.

## Inventario das telas

A tabela lista os destinos efetivos no Rio Branco. Os testes comparam as telas
`data-page` de Tecnologia/Chamados e os links originais da Automacao com o HTML
do menu, inclusive no perfil Nanotech. Subtelas de backup sao exigidas uma a uma.

| Modulo | Menu | Funcao | Destino | Recurso |
| --- | --- | --- | --- | --- |
| Tecnologia | dashboards | Visao geral | `/apps/tecnologia#dashboard` | `dashboard` |
| Tecnologia | dashboards | Visao de backups | `/apps/tecnologia#backup-visao` | `backup` |
| Tecnologia | cadastros | Equipamentos | `/apps/tecnologia#equipamentos` | `equipamentos` |
| Tecnologia | cadastros | Planos de backup | `/apps/tecnologia#backup-planos` | `backup` |
| Tecnologia | cadastros | Instalar agentes de backup | `/apps/tecnologia#backup-agentes` | `backup` |
| Tecnologia | cadastros | Descobrir impressoras | `/apps/tecnologia#descoberta-impressoras` | `equipamentos` |
| Tecnologia | cadastros | Descobrir computadores | `/apps/tecnologia#descoberta-computadores` | `equipamentos` |
| Tecnologia | relatorios | Historico | `/apps/tecnologia#historico` | `historico` |
| Tecnologia | relatorios | Ocupacao do link | `/apps/tecnologia#ocupacao-link` | `historico` |
| Tecnologia | docs | Agentes e protocolos | `/apps/tecnologia#protocolos` | `equipamentos` |
| Tecnologia | monitor | Monitoramento de link | `/apps/tecnologia#monitor-link` | `dashboard` |
| Tecnologia | monitor | Monitoramento de backups | `/apps/tecnologia#backup-visao` | `backup` |
| Tecnologia | configurar | Configuracao e alertas | `/apps/tecnologia#config` | `config` |
| Tecnologia | configurar | Planos de backup | `/apps/tecnologia#backup-planos` | `backup` |
| Tecnologia | configurar | Instalar agentes de backup | `/apps/tecnologia#backup-agentes` | `backup` |
| Automacao | dashboards | Dashboard Automacao | `/apps/automacao/` | `*` |
| Automacao | dashboards | Maquinas Automacao | `/apps/automacao/maquinas` | `*` |
| Automacao | cadastros | Equipamentos e tipos - Motores | `/apps/automacao/motores` | `*` |
| Automacao | cadastros | Equipamentos e tipos - Drivers | `/apps/automacao/sensores/drivers` | `*` |
| Automacao | cadastros | Setores | `/apps/automacao/setores` | `*` |
| Automacao | monitor | Tempo real | `/apps/automacao/tempo-real` | `*` |
| Automacao | gestao | Historico | `/apps/automacao/historico` | `*` |
| Automacao | gestao | Alarmes | `/apps/automacao/alarmes` | `*` |
| Automacao | docs | Manuais das maquinas | `/apps/automacao/documentacao` | `*` |
| Automacao | workflow | Kanban Automacao | `/workflow/automacao` | `*` |
| Chamados | dashboards | Indicadores de Chamados | `/apps/chamados?view=dashboard` | `dashboard` |
| Chamados | relatorios | Histórico de Soluções | `/apps/chamados?view=historico` | `historico` |
| Chamados | workflow | Chamados e Manutenções | `/apps/chamados?view=chamados` | `chamados` |
| Chamados | gestao | Agenda de Tarefas | `/apps/chamados?view=agenda` | `agenda` |
| Chamados | docs | Manuais e Documentações | `/apps/chamados?view=documentos` | `documentos` |

## Acoes preservadas nas telas

- Tecnologia: cadastro/edicao de equipamento, detalhes e impressoes, descoberta
  manual, coleta e teste de velocidade, alertas, relatorio de ocupacao, plano de
  backup, forcar backup, editar, novo JSON, exclusao e instaladores.
- Automacao: detalhes e edicao de motores/drivers, tags, leituras de maquinas,
  guias e PDFs continuam acessiveis pelas telas de origem.
- Chamados: fila, indicadores, agenda, historico e documentos; detalhes,
  intervencoes, anexos e edicoes continuam contextuais.

A auditoria de menu nao executa acoes de negocio. Backup/restore, envios de
e-mail e varreduras reais nao foram executados para testar os atalhos.

## Acessos e carregamento

Os cinco recursos existentes de Tecnologia recebem nomes explicitos no catalogo.
O servidor confere os recursos nas APIs; o shell recebe somente as concessoes
atuais e recusa hashes sem acesso. Um usuario apenas de backup consulta somente
as APIs de backup. Administrador e acesso integral continuam sujeitos ao contrato.
Nenhuma permissao foi concedida ou gravada.

Historico recarrega depois da lista de equipamentos, corrigindo a abertura
direta antes do overview. Velocidade continua consultavel sem equipamento
selecionado. O monitor de link exibe os dados existentes sem acionar novo teste.

## Verificacao

- `tests/test_module_tasks.py`: cobertura por telas de origem nos dois perfis,
  catalogo, sessao, contrato, autorizacao e recusa das APIs por recurso.
- `tests/check_module_tasks.py`: paginas em 1440 e 390 pixels, tarefa unica,
  planos/execucoes/link/historico com dados sinteticos e usuarios restritos.
- `tests/check_menu_pdf.py`: navegacao e compatibilidade dos paineis de backup.
- Suites de Tecnologia, menu PDF, navegacao e acesso unificado.

### Resultado confirmado em 16/09/2026

117 testes unitarios passaram nas suites de tarefas (8), menu PDF (11),
Tecnologia (74), navegacao (14) e acesso unificado (10). O navegador verificou
52 aberturas de paginas em desktop/celular, alem dos casos com recursos restritos
de backup, dashboard e historico. A suite de menu PDF tambem passou.

`./up.sh` concluiu a reconstrucao local e os healthchecks. Log:
`/tmp/nanotech-menu-repair-up.log`. A verificacao autenticada por HTTPS confirmou
monitoramento de link com dados, as tres telas de backup e historico; healthz,
backup/jobs, overview e link-usage-history retornaram 200. Os SHA-256 de app.py,
dois manifests e HTML/JS de Tecnologia no container coincidiram com o workspace.
Log: `/tmp/nanotech-menu-repair-live.log`. A verificacao usou apenas GET.

Nao houve restauracao/sincronizacao de bancos nem execucao manual de backup.
As concessoes dos usuarios foram preservadas. As alteracoes estao aplicadas
localmente, sem commit/push desta revisao e sem publicacao no Render.
HEAD e origin/main consultados: `c39540724f33008cd8e77323adf31efccc92a29b`.
