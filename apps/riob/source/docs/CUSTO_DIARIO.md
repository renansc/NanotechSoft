# Custo diario por grupo

GESTAO > RioB > Custos diarios por grupo (`#custoDiario`) apura o custo de
produtos PET/retornaveis com a producao boa realmente realizada no dia. Nao
cria movimentos de estoque, compras ou lancamentos financeiros.

## Lancamento

1. Escolha a data (de 2000 ate hoje, America/Sao_Paulo).
2. Informe cada produto produzido, quantidade de embalagens boas, volume em ml
   por embalagem e quantidade de embalagens por pacote/caixa. Produto e grupo
   vem do cadastro existente; volume e pacote sao sugeridos pelas regras
   existentes, mas devem ser conferidos. Embalagem significa uma garrafa.
3. Informe os gastos correspondentes ao dia: pessoal, embalagem adicional,
   agua, energia e outras despesas. Cada linha tem descricao, setor e valor
   total em reais, para um grupo especifico ou compartilhado entre os grupos.
   Contas mensais nao sao rateadas automaticamente: informe a parcela do dia.
   Nao repita itens de embalagem ou despesas que ja estao na formula.
4. Confira as faltas das contagens finalizadas, apresentadas automaticamente.
5. Apurar e salvar dia persiste a producao, as despesas e a referencia da formula.

Nao ha folha salarial, apontamento de horas ou coletor de producao integrado
nesta etapa. Linhas de despesa nao informadas nao acrescentam custo. Dia sem
producao mantem seus gastos pendentes de rateio, sem dividir por zero.

## Calculo e historico

- Litros bons = embalagens boas * volume_ml / 1000.
- Pacotes equivalentes = embalagens boas / embalagens_por_pacote. Fracoes sao
  equivalentes de custo, nao pacotes fisicamente fechados.
- Formula: receita atual do produto/xarope com a ultima referencia XML
  disponivel ate a data escolhida, proporcional aos litros produzidos.
- Pessoal e demais gastos exclusivos de um grupo sao distribuidos pelos
  litros bons dos produtos daquele grupo.
- Gastos compartilhados sao distribuidos pelos litros bons de todos os grupos.
- Custo total / litros, / embalagens e / pacotes fornece as tres unidades.
- Dashboard apresenta cada componente nas tres unidades ou em reais totais.
  A media do grupo e ponderada pela producao e pode misturar apresentacoes;
  a tabela por produto identifica volume e capacidade do pacote.

`custo_diario_lancamentos` guarda um documento por data, revisao, ator, data de
alteracao, producao/despesas, resultado e referencias da formula/xarope. As
referencias de receita e precos de insumos sao preservadas em consultas futuras.
Salvar novamente recalcula usando as receitas atuais e os precos ate a data.
Gravacao concorrente retorna 409 e conserva o rascunho. A transacao compartilha
o bloqueio da base de xarope com o editor de formulas.

## Desperdicio: somente faltas de inventario nesta etapa

Conforme definido pelo usuario em 23/09/2026, nao ha lancamento manual de perda
de producao. Sao lidas `estoque_contagens` finalizadas na data escolhida e suas
linhas de `estoque_contagem_resultados` com `desperdicio > 0`. Contagens em
conferencia, sobras, diferenca zero e outras datas nao entram. Cada linha e
identificada por item/contagem; consultar ou salvar custos nao efetua nova baixa.

Como a contagem existente nao identifica setores da fabrica, os agrupamentos
sao **Estoque / grupo cadastrado**. Nao se inventa setor produtivo. Perdas de
producao e seus setores serao uma etapa futura.

Falta de produto acabado PET/GFA usa custo da formula por garrafa. Falta de
insumo com unidade de estoque conhecida (kg/g/l/ml/un) usa o preco XML ate a
data e a conversao existente. Nao usa preco de venda nem valor arbitrario do
ajuste de estoque. Cadastro/unidade/preco sem referencia valida deixa valor e
custo completo pendentes. Grupos sem formula, como agua, ficam pendentes.
Perdas de PET/GFA sao rateadas no proprio grupo; perdas de insumos e outros
grupos entram como compartilhadas. Quantidades de unidades diferentes nao se
somam. Sobras nao compensam nem geram desperdicio negativo.

As contagens sao atualizadas a cada consulta, inclusive quando foram finalizadas
apos salvar o dia. O dashboard reapura essa parcela sobre a producao/despesas e
referencias de receita salvas; a valoracao dos insumos faltantes consulta os XMLs
ate a data. Portanto novas contagens ou referencias de perda podem atualizar o
custo exibido, sem mudar producao/despesas salvas ou duplicar contagens.

## Telas, APIs e autorizacao

- GESTAO > Custos diarios por grupo: recurso novo `riob:custo_diario`.
  `GET /api/custo-diario?data=YYYY-MM-DD` retorna cadastro, dia e contagens.
  `PUT` na mesma URL recebe `revisao` e `dados` com `producao` e `despesas`.
  `perdas` manual nao vazio e recusado; a origem e sempre a contagem finalizada.
- DASHBOARD > Custo do produto: consulta padrao Custo do dia por grupo; seletor
  mantem Evolucao mensal da formula. `GET /api/custo-diario/dashboard?data=...`
  usa o recurso existente `riob:custo_produto_dashboard`.
- Catalogo de Config > Usuarios e acessos e ambos os perfis do manifest incluem
  as funcoes. Consulta nao libera editar, e editar nao libera o dashboard.
  Leitura das faltas para custeio nao autoriza finalizar contagens ou alterar
  estoque. Proxy e blueprint verificam permissoes e bloqueios individuais.
- Login unico, sem concessoes automaticas. Render permanece somente leitura.
- Ate 200 linhas por colecao; quantidades/valores finitos, nao negativos e ate
  seis casas; embalagens/capacidade exigem inteiros positivos; sem produto
  duplicado. Setor e descricao sao obrigatorios, com ate 180 caracteres.

Testes: `tests/test_custo_diario.py` no app; `tests/check_custo_diario.py` e
`tests/test_custo_produto_access.py` na raiz. Cobrem rateio, unidades, datas,
contagens posteriores, ausencia de preco/producao, revisoes, acessos e celular,
com dados sinteticos e sem gravar receitas ou producao no banco operacional.
