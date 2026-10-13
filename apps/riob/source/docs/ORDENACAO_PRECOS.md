# preço med.varia por cidade e produto

Desde 07/10/2026, os totais RioB/CLT/Autonomos ficam ao lado do submenu no PC.
A linha seguinte contem datas inclusivas, Atualizar relatorio, Limpar filtros,
Vendedor e Grupo. Nao exibe seletor de mes nem Limpar periodo. Sem datas, o
servidor resolve o ultimo mes disponivel e a tela preenche o intervalo; apenas
um limite informado continua um intervalo aberto. Limpar filtros restaura o
ultimo mes, todos os vendedores e todos os grupos.

O titulo Variacao de preco e os indicadores ocupam uma linha no PC. A tabela
mostra cidade, produto, minimo, maximo e numero de PDVs, sem repetir vendedor,
grupo ou periodo. Clicar na linha ou no botao de PDVs abre um dialogo nativo;
Escape ou Fechar encerra a consulta visual. Preco medio aparece somente nesse
popup, para a cidade/produto/grupo escolhidos e os filtros carregados.

## Consultas e calculos

`GET /api/vendas/relatorio?visao=precos_cidade&tipo_relatorio=variacao_preco`
retorna `linhas`, `resumo_geral`, `grupos_disponiveis`, `vendedores`,
`cabecalho_resumo`, `filtros` e metadados do cache. Parametros opcionais:
`data_inicio`, `data_fim`, `vendedor`, `grupo`. Os totais superiores preservam
as regras financeiras comuns e respeitam vendedor, grupo e periodo.

Para detalhes, adicionar `detalhe=1`, `cidade`, `produto` e `grupo` (os tres
obrigatorios). O popup consulta separadamente os tipos `variacao_preco` e
`preco_medio` autorizados, com os mesmos filtros, unindo PDVs por `chave`.
O payload inclui `pdvs` e uma linha com o resumo da selecao. O tipo medio
nunca devolve minimos/maximos; variacao nunca devolve medias. Usuario liberado
somente para preco medio ve a lista de cidades/produtos/PDVs sem min/max.

A consulta agrega todos os itens elegiveis no SQL, sem depender da amostra
limitada do relatorio antigo. Cidade/produto usam texto aparado em maiusculas;
cliente usa `cliente_norm`, com fallback para nome. A linha tem identidade
cidade/produto/grupo, com agrupamento e filtro binarios consistentes: grafias
diferentes por acento permanecem separadas. Astuba conserva grupo separado. Vendedores Balcao/Outros
e bonificacoes ficam fora dos precos; devolucoes nao entram em min/max.

Os PDVs listados possuem ao menos uma venda sem devolucao para essa linha.
O preco medio de cada PDV e a soma de valor vendido menos devolvido dividida
pela soma de quantidade menos devolvida. A media da cidade/produto usa esses
mesmos PDVs e totais ponderados, nunca media das medias. Devolucoes desses PDVs
entram na base liquida; PDVs somente com devolucao ficam fora da linha e do
popup. Mantem a classificacao de preco medio existente: categoria Outros nao
possui media. Quantidade liquida nao positiva gera `null`, exibido como traco.
A base usa Decimal e arredonda o resultado em duas casas.

Os filtros sao parametros SQL vinculados. O cache distingue visao, tipo,
periodo, vendedor, grupo, cidade, produto e detalhe, alem da revisao da base.
Ao abrir o popup, mudanca nos metadados da importacao exige atualizar a lista.
Respostas antigas nao substituem filtros novos, reabrem um popup fechado ou
reaparecem ao trocar de aba. Uma falha parcial mostra os dados do outro tipo
com aviso; o inicio de uma nova consulta elimina os resultados anteriores.

## Ordenacao no popup

Nome, Valor: preco medio, Valor: minimo e Valor: maximo aparecem conforme os
tipos consultados com sucesso e autorizados. A direcao pode ser crescente ou
decrescente. Ordenar nao consulta a API nem recalcula valores.

Zero numerico e valido. Valores ausentes/invalidos ficam ao final nas duas
direcoes. Textos usam `Intl.Collator('pt-BR')` com ordem numerica natural,
ignorando diferencas de acento/caixa. Empates sao estaveis e o array original
nao e modificado. O grupo que define os valores e o da linha selecionada;
o filtro de grupo fica na tela principal.

## Acessos e compatibilidade

Config > Usuarios e acessos conserva `riob:vendas` e as chaves individuais:
`#vendas:variacao_preco` (Variacao por cidade e produto) e
`#vendas:preco_medio` (Preco medio nos PDVs e PDF). Ambas abrem a mesma aba;
liberar uma nao libera a outra. O servidor valida tipo/alias e recurso.
`origem=dashboard` nao contorna a permissao desta visao. A ordenacao usa apenas
os dados autorizados ja recebidos. Nao ha concessao automatica nem escrita.

As consultas antigas sem `visao=precos_cidade`, dashboard e API de PDF conservam
seus contratos e calculos. O PDF antigo por categorias nao e exibido como
exportacao desta nova tabela por produto.

## Validacao

- `tests/check_preco_med_varia.py`: layout real em 1280/1440 e celular, filtros,
  popup, consultas consistentes, media, ordenacao local, acesso parcial/negado,
  falhas, concorrencia e escape de HTML importado.
- `tests/test_vendas_ordenacao.js`: numeros, zero, ausentes, texto, empates e
  imutabilidade da funcao de ordenacao.
- `tests/test_vendas_reports_access.py`: proxy, tipos, aliases, detalhe,
  origem dashboard, PDF e catalogo em ambos os perfis.
- `apps/riob/source/tests/test_vendas_precos_cidade.py`: validacao de entrada e
  SQL real opcional com `RB_REPORT_TEST_MYSQL=1` e `DB_*`. Usa exclusivamente
  tabela temporaria e dados sinteticos, incluindo devolucoes, bonificacao,
  filtros, media ponderada, limites inclusivos, Astuba e mais de 300 PDVs.
- `tests/check_vendas_reports.py` e `tests/test_vendas_reports_frontend.js`:
  navegacao entre relatorios, cabecalho, periodo e concorrencia existentes.
