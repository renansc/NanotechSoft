# Chamados

Módulo integrado ao portal para registrar requisições e manutenções de TI,
predial, elétrica, hidráulica, mecânica, segurança e outras áreas. O frontend
fica em `apps/chamados/source`; rotas e tabelas fazem parte do portal.

## Dados reutilizados

- solicitantes, responsáveis e autores vêm de `usuarios`;
- equipamentos vêm de `tecnologia_dispositivos`;
- um chamado pode existir sem equipamento, para ocorrências prediais;
- documentos podem ser gerais, vinculados a um equipamento ou anexados a um chamado.

## Fluxo

1. Abra o chamado com categoria, prioridade, descrição e sintomas.
2. Vincule solicitante, responsável e equipamento quando aplicável.
3. Registre diagnóstico, trabalho executado, tempo gasto e mudanças de status.
4. Para resolver ou fechar, informe obrigatoriamente a medida resolutiva.
5. O histórico passa a alimentar a busca de casos semelhantes. Chamados com
   medida resolutiva registrada aparecem no Histórico de soluções, mesmo antes
   do fechamento; somente casos resolvidos ou fechados alimentam as sugestões
   automáticas apresentadas durante o atendimento.

Os dados do chamado e os registros de intervenção podem ser corrigidos pela
tela de detalhes. Ao editar uma solução no histórico, o resumo resolutivo do
chamado é atualizado a partir da solução mais recente.

Manuais e documentações gerais também podem ser editados. É possível corrigir
metadados e links ou substituir o arquivo; sem um novo arquivo, o anexo atual é
preservado.

## Agenda de tarefas e avisos

A aba **Agenda de tarefas** registra tarefas, orçamentos, reuniões, retornos e
outros compromissos. Cada item possui data/hora, antecedência do lembrete,
um ou mais destinatários e vínculo opcional com chamado. Tarefas podem ser
editadas, concluídas, canceladas e reabertas.

O lembrete usa o mesmo SMTP local dos alertas do módulo Tecnologia: primeiro as
variáveis `SMTP_*` do ambiente e, quando elas não estiverem configuradas, uma
conta ativa do Gestor de E-mails do RioB. `CHAMADOS_AGENDA_ENABLED=1` mantém o
verificador ativo e `CHAMADOS_AGENDA_INTERVAL_SECONDS` controla o intervalo,
com mínimo de 15 segundos. Falhas ficam visíveis no item e são tentadas
novamente após 15 minutos; a mensagem nunca é marcada como enviada antes da
confirmação do SMTP.

Cada deploy grava a agenda no próprio banco local. O perfil Nanotech não recebe
mais os usuários e equipamentos de demonstração do Rio Branco. Registros
legados criados automaticamente continuam preservados no banco, mas são
ocultados dos seletores do Chamados fora do perfil `rio-branco`.

Status disponíveis: `ABERTO`, `TRIAGEM`, `EM_ATENDIMENTO`, `AGUARDANDO`,
`RESOLVIDO`, `FECHADO` e `CANCELADO`.

## Sincronização com o Kanban do Conky

O módulo reconcilia os chamados ativos com o arquivo JSON lido pelo Conky. A
sincronização é bidirecional: uma tarefa criada com `kanban.py add` abre um
chamado de categoria TI e prioridade média; chamados criados no portal entram
automaticamente no Conky. Alterações de título e de coluna feitas no Conky são
registradas no histórico do chamado.

O número exibido antes do título é sempre o ID do chamado. Por exemplo, mover
o item `12` altera o chamado `CH-AAAA-000012`; a numeração não muda quando a
lista é reordenada.

O mapeamento de status é:

| Conky | Chamados |
| --- | --- |
| Aberto | `ABERTO` ou `TRIAGEM` |
| Em atendimento | `EM_ATENDIMENTO` |
| Aguardando | `AGUARDANDO` |

Como o Conky possui somente três colunas, chamados `RESOLVIDO`, `FECHADO` ou
`CANCELADO` deixam de ser exibidos nele. Se forem reabertos no portal, voltam a
aparecer. `TRIAGEM` é exibido em Aberto e continua como `TRIAGEM` até a coluna
ser alterada no Conky.

No Compose integrado deste host, portal e script usam por padrão
`/srv/conky/kanban-tasks.json`. O diretório é montado no container do portal e
permanece como dado de execução fora do Git. Ao executar o script em outro
diretório, aponte ambos para o mesmo arquivo:

```bash
export KANBAN_TASKS_FILE=/caminho/kanban-tasks.json
export CHAMADOS_KANBAN_FILE=/caminho/kanban-tasks.json
```

Quando o portal estiver em container, monte também o diretório do host em
`/srv/conky` por meio de `CHAMADOS_KANBAN_HOST_DIR`.

`CHAMADOS_KANBAN_ENABLED=1` liga o reconciliador e
`CHAMADOS_KANBAN_INTERVAL_SECONDS` define o intervalo (mínimo de cinco
segundos). Cada tarefa recebe uma `syncKey` persistente; a tabela
`chamados_conky_sync` usa essa chave para impedir chamados duplicados mesmo
quando uma execução é interrompida.

## Sugestões e base de conhecimento

A busca local compara categoria, subcategoria, equipamento, tipo do equipamento
e termos relevantes do problema. Somente chamados resolvidos ou fechados são
usados como solução sugerida. Manuais gerais ou ligados ao equipamento também
aparecem nas recomendações. O cálculo não envia dados a serviços externos.

## Documentos

São aceitos PDF, imagens, texto, Markdown, documentos e planilhas com até 15 MB,
além de links HTTP/HTTPS. Arquivos de execução ficam em
`apps/chamados/uploads`, ignorados pelo Git. Eles devem entrar na rotina de
backup de dados do servidor separadamente do código.

## Rotas principais

- `GET /apps/chamados/api/bootstrap`: usuários, equipamentos e indicadores.
- `GET|POST /apps/chamados/api/agenda`: lista e agenda tarefas com aviso.
- `PUT /apps/chamados/api/agenda/<id>`: edita, conclui, cancela ou reabre uma tarefa.
- `GET|POST /apps/chamados/api/tickets`: lista ou abre chamados.
- `GET|PUT /apps/chamados/api/tickets/<id>`: detalhe e atualização.
- `POST /apps/chamados/api/tickets/<id>/interventions`: histórico e tempo.
- `PUT /apps/chamados/api/tickets/<id>/interventions/<intervention_id>`: corrige
  um registro do histórico e sua solução.
- `GET /apps/chamados/api/similar`: casos e documentos semelhantes.
- `GET|POST /apps/chamados/api/documents`: manuais e anexos.
- `PUT /apps/chamados/api/documents/<id>`: edita metadados, link ou arquivo.
- `GET /apps/chamados/api/documents/<id>/download`: arquivo ou link protegido.

O login e as permissões são sempre os do portal.

## Menu Rio Branco

No perfil `rio-branco`, Indicadores ficam em Dash, Manuais e Documentacoes em
Documentos, Historico de Solucoes em Relatorio, Chamados e Manutencoes em Workflow
e Agenda de Tarefas em Gestao. Manuais foram movidos de Cadastro para Documentos
em 14/09/2026; o recurso `documentos`, arquivos e rotas existentes sao preservados.
Consulte `docs/MENU_RIO_BRANCO_PDF.md`.

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
