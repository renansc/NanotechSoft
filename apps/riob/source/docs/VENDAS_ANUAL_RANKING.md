# Vendas anual: ranking e vendas em popup (08/10/2026)

O relatorio anual usa o mesmo cabecalho compacto de preço med.varia:
RioB/CLT/Autonomos ao lado do submenu no PC; datas, Atualizar relatorio,
Limpar filtros, Vendedor e Cliente na linha abaixo. Limpar filtros tambem limpa
as datas e restaura Todos nos seletores. Nao ha um segundo botao Limpar periodo.
As demais abas conservam seu comportamento, inclusive o layout do mix.

## Ranking

Com Todos os vendedores, lista vendedores. Ao escolher um vendedor, lista
somente seus clientes. A lista do seletor Cliente tambem fica restrita aos
clientes relacionados ao vendedor nas vendas importadas dentro do intervalo.
Com Todos, mostra a uniao dos clientes. Opcoes de clientes nao sao restringidas
pelo proprio filtro Cliente. Trocar vendedor limpa imediatamente esse filtro;
se uma mudanca de datas retirar o cliente selecionado, a tela limpa e consulta
novamente. Falhas nao restauram opcoes ou resultados de consultas anteriores.

A medida de classificacao e a diferenca em hectolitros: atual menos anterior.
Maior perda primeiro ordena a diferenca crescente; o sentido inverso ordena
decrescente. Crescimentos aparecem depois das perdas no primeiro sentido.
O ranking mantem valores anteriores, atuais, diferenca e percentual. Sem base
anterior, a variacao percentual continua nula (Sem base). Ordenar e local,
estavel e nao altera o payload recebido nem dispara uma nova consulta.

As regras do comparativo mensal permanecem: referencia e o ultimo dia da base
no intervalo, independente do vendedor/cliente; compara o ano dessa referencia
com o anterior, somente ate seu ultimo mes. Meses futuros nao viram perdas.
Datas inicial/final sao limites inclusivos aplicados aos registros dos dois
anos, sem deslocamento automatico de datas para o ano anterior. Sem datas,
consulta os dois anos ate o mes de referencia. Preserva a conversao e o round
Python por item em hectolitros, incluindo negativos; nao substitui por SUM/100.
Balcao/Outros e tab_venda 91 ficam fora do comparativo/ranking.

## Popup

Clicar em uma linha ou em Ver vendas abre um dialogo nativo com as vendas do
vendedor/cliente selecionado, preservando os filtros carregados. Exibe data,
NF, vendedor, produto, volume em hl e valor de venda; o resumo mostra volume
e valor vendido dos dois anos. Valores monetarios sao valor_venda, nao liquido.
A lista e paginada em 100 itens, com Anterior/Proxima e ordem data/id decrescente;
nao ha corte silencioso nos resultados. Escape ou Fechar fecha o popup.

Uma nova consulta ou troca de aba fecha e invalida o popup. Respostas antigas
nao substituem filtros novos nem reabrem dialogos fechados. A revisao da base
no detalhe deve corresponder a do resumo; nova importacao exige atualizar.
Nomes importados sao escapados no HTML.

## API, desempenho e acessos

Reutiliza `GET /api/vendas/relatorio?tipo_relatorio=percentual_vendas_anual`.
`visao=anual_clientes` habilita `ranking` e `ranking_tipo` (vendedor/cliente).
Cada linha inclui chave, nome, tipo, total_atual/anterior, diferenca_volume,
variacao_percentual, movimento, venda_atual/anterior e itens. O nome interno
da visao nao limita o ranking a clientes.

Para vendas: mesma visao com `detalhe=1`, `vendedor` ou `cliente` e `pagina`
(inteiro positivo). Retorna tambem vendas, pagina, por_pagina e tem_proxima.
Os filtros sao vinculados no SQL. O ranking usa histogramas compactos por
entidade/mes/litros, sem carregar todo o historico de itens em Python. O popup
consulta apenas a pagina. Opcoes agrupadas guardam a relacao vendedor/cliente
no cache, preservando a referencia global. Cache distingue filtros, visao,
detalhe, pagina e revisao da importacao.

Config > Usuarios e acessos conserva `riob:vendas` e a chave individual
`/apps/riob#vendas:relatorio_anual`, nomeada Vendas Anual RioB - ranking e vendas
em popup. Sem novas concessoes. O proxy valida o tipo anual e aliases; ranking
e detalhe exigem o item do relatorio mesmo com origem=dashboard. O dashboard
anual usa origem=dashboard e seu proprio item de menu. Sessao e contrato
continuam unicos e obrigatorios. Nao ha migracao, escrita ou sincronizacao.

## Validacao

- `tests/check_vendas_anual.py`: layout em 1280/1440 e celular, seletores,
  ordenacao nos dois sentidos, popup, paginacao, respostas antigas, falhas,
  acesso negado e revisao de importacao.
- `tests/test_vendas_reports_access.py`: tipos/aliases anuais, ranking/detalhe,
  dashboard separado, acessos autorizados e negados nos dois perfis.
- `apps/riob/source/tests/test_vendas_anual_ranking.py`: SQL real opcional com
  RB_REPORT_TEST_MYSQL=1 e DB_*, usando exclusivamente tabela temporaria.
  Compara ranking/resumo/detalhe, carteira por vendedor, cache, ano parcial,
  arredondamento por item, filtros e paginas sem duplicacao.
- `test_vendas_relatorio_anual.py`, `test_vendas_relatorios_performance.py` e
  `tests/test_vendas_reports_frontend.js`: regras anuais, opcoes e concorrencia.
- `tests/check_vendas_reports.py` e `tests/check_preco_med_varia.py`: regressao
  de navegacao e do cabecalho compartilhado com os demais relatorios.

O suporte de testes resolve resumo_carteira apenas quando o mix o utiliza;
ausencia preexistente desse simbolo nao impede carregar os testes anuais.
