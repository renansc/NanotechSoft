# Unificar os relatorios na tela preço med.varia

Pedido do usuario: unir os relatorios Variacao de Preco e Preco Medio na mesma
tela, chamada exatamente **preço med.varia**, no RioB do /srv/nanotechsoft.

## Tarefa para o executor com acesso ao repositorio

Implemente a uniao dos dois relatorios em uma unica aba de
Relatorios > RioB > Vendas. A tela deve mostrar as informacoes dos dois
relatorios simultaneamente, em secoes identificadas, com filtros compartilhados
de periodo, vendedor e cliente/PDV quando aplicaveis. Nao basta renomear uma
aba nem criar duas subabas que continuem separando os relatorios.

Antes de analisar ou editar, leia integralmente AGENTS.md,
docs/AI_RESEARCH_MANUAL.md, README.md e apps/riob/source/docs/AI_CONTEXT.md.
Consulte apps/riob/source/docs/API_E_DADOS.md, especialmente a secao 5.1,
e docs/ACESSOS_POR_ITEM_MENU.md. Confira git status --short e preserve todas
as alteracoes existentes: ha trabalho ainda nao commitado neste checkout.

O manifest apps/riob/app.json confirma source_dir=apps/riob/source.
Localize as implementacoes com rg antes de criar qualquer funcao ou arquivo:

- RioBranco.html: vendasRelTabVariacao, vendasRelTabPrecoMedio e os paineis
  Variação de Preço, Preço Médio e Preço Médio por Cidade e Cliente.
- script.js: setVendasRelatorioModo, os modos variacao_preco e preco_medio,
  seus carregadores, filtros, renderizadores, cache e exportacao PDF.
- server.py: GET /api/vendas/relatorio, tipos variacao_preco/preco_medio
  e a rota existente do PDF de preco medio.
- apps/riob/app.json, app.py e menu_access.py: catalogo, aliases e autorizacao.
- tests/test_vendas_reports_access.py, tests/test_vendas_reports_frontend.js,
  tests/check_vendas_reports.py e testes de relatorios em
  apps/riob/source/tests/.

## Requisitos de implementacao e aceite

1. Exibir uma unica aba com o nome exato preço med.varia. Reaproveitar os
   componentes dos dois relatorios, incluindo detalhes, graficos e tabelas
   existentes, evitando duplicacao de cabecalho e de filtros equivalentes.
2. Ambos os blocos devem usar o mesmo periodo inclusivo. Datas prevalecem
   sobre mes; definir um unico periodo efetivo tambem quando nao ha datas,
   pois hoje variacao usa mes e preco medio pode usar toda a base ativa.
   Preservar o filtro ao navegar e enviar os mesmos parametros ao PDF.
3. Preservar as formulas atuais, ponderacoes e regras de bonificacao.
   Manter RioB/CLT/Autonomos, os tres autonomos atuais, a exclusao de
   Balcao/Outros e Astuba 2L separado de PET 2L nos precos e variacoes.
   Nao somar resultados agregados de fontes distintas nem alterar importacoes.
4. Reutilizar APIs e consultas existentes quando possivel. Impedir que
   respostas atrasadas sobrescrevam filtros recentes. Mostrar estados de
   carregamento, erro e ausencia de dados por secao sem exibir dados antigos
   como se fossem do periodo atual. Manter layout legivel no celular.
5. Manter links antigos #vendas:variacao_preco e #vendas:preco_medio
   compativeis com a tela unificada, preservando os bloqueios individuais.
   A uniao nao pode liberar uma secao que o usuario nao podia consultar.
   Atualizar o manifest nos perfis pertinentes, o catalogo de
   Config > Usuarios e acessos, os controles do servidor e a documentacao.
   Reutilizar riob:vendas sem conceder acessos automaticamente; testar
   usuarios com ambas as secoes, apenas uma e nenhuma, inclusive APIs e PDF.
6. Atualizar testes relevantes: aba unica, dois blocos, igualdade de filtros,
   aliases, periodo vazio/invalido, concorrencia de respostas, PDF e acessos.
   Usar dados sinteticos. Informar os comandos realmente executados e resultados.
7. Preservar login/sessao unicos, isolamento entre clientes e Render somente
   leitura. Nao criar scripts de deploy, operar dados, restaurar/sincronizar
   bancos, reimportar arquivos, publicar, fazer commit/push ou deploy nesta tarefa.

Entregar diff revisavel, documentacao atualizada e resultados dos testes.
Nao afirmar que arquivos foram alterados ou testes executados sem evidencia.

## Limite desta chamada ao Ollama

Esta chamada de inferencia nao fornece ferramentas de filesystem ou shell ao
modelo. Portanto, processe a tarefa e devolva uma orientacao tecnica concisa
para o executor, com os pontos de integracao e riscos de permissoes/periodos.
Declare que a implementacao depende do executor com acesso ao repositorio.
Nao invente um diff a partir de arquivos que nao foram fornecidos e nao afirme
ter aplicado a mudanca. Este prompt registra a tarefa de implementacao completa.
