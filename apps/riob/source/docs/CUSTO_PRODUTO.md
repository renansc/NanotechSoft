# Custo do produto e base de xarope

GESTAO > RioB > Custo do produto abre `/apps/riob#custoProduto`. O cadastro
central `estoque_produtos` fornece tanto os produtos acabados ativos PET/GFA
quanto os ingredientes selecionaveis. Nao existe cadastro paralelo de itens.

## Uso

1. Abra **Cadastrar / editar base de xarope**. Selecione os ingredientes do
   cadastro existente, informe quantidades, unidades e o **rendimento
   da receita em litros de xarope**. Esse rendimento pode ser diferente de 1000 L.
2. Salve a base. O sistema calcula o custo da receita e o custo por litro de
   xarope. Ela e compartilhada por todos os sabores e apresentacoes.
3. Abra a formula de um produto. Informe o **consumo de xarope em litros para
   produzir 1000 litros de bebida acabada**. Cada produto tem sua propria dose.
4. Confira o volume da garrafa e selecione os ingredientes adicionais do produto
   (concentrados, aromas, embalagens etc.). Nao repita os ingredientes que ja
   estao no xarope. Um produto pode ter apenas xarope, sem itens adicionais.
5. Salve. A lista mostra o custo estimado por 1000 L e por garrafa. Alterar a
   receita/rendimento do xarope ou importar uma nova compra recalcula as estimativas dos produtos,
   sem copiar ingredientes da base para cada formula.

A selecao mostra nome e ID do cadastro. O preco e automatico e somente leitura:
usa o valor unitario da ultima **NF-e de fornecedor importada**, pela data de
emissao, ate a data atual no fuso America/Sao_Paulo. A tela identifica numero,
data e unidade da nota. Valores antigos ou enviados pelo navegador sao ignorados.

A fonte e `importar_xml_estoque_itens`, com `ENTRADA_ESTOQUE` e
`ENTRADA_FORNECEDOR`. O vinculo confirmado em `estoque_movimentos` tem prioridade;
notas seguintes reaproveitam fornecedor/codigo do XML confirmado. Quando o
emitente muda, codigo E descricao XML identicos a uma entrada confirmada
tambem identificam o cadastro, desde que nao ambiguos. Isso preserva o vinculo
quando o nome do produto foi abreviado/renomeado. Na ausencia desses vinculos, usa alias tipado `nfe_entrada` de `estoque_produto_codigos` ou
nome exato normalizado e nao ambiguo. Codigos numericos de fornecedores nao sao
comparados diretamente com codigos genericos de outros cadastros. Notas
marcadas como descartadas, transferencias, devolucoes e bonificacoes
nao fornecem preco. Remessas comuns ficam excluidas; entradas de fornecedor
com CFOP 5923/6923 e natureza contendo venda a ordem fornecem a referencia
do XML (caso observado do acucar). Nao e necessario criar pedido em Compras. Ajustes de saldo nao sao compras. Reimportacoes da mesma
nota/item sao desduplicadas e uma nota antiga nao substitui a compra mais recente.

Conversoes tonelada (T/TO/TON)/kg/g, l/ml e milheiro/unidade sao automaticas.
O fator de embalagem ja cadastrado no estoque tambem e aproveitado quando
maior que 1 e a unidade de compra coincide com a unica apresentacao confirmada
para esse produto. Exemplo: acucar em saco, cadastro em KG com fator 50,
resulta em 50 kg por saco. Se mudar a unidade de compra, nao reaplica esse fator.
Conversao explicita da formula tem prioridade sobre o fator do cadastro. Para sacos, bombonas
ou outras embalagens, informe **quantos kg, litros ou unidades da formula ha
em uma embalagem comprada**. Exemplo: bombona de 25 L por R$ 250 resulta em
R$ 10/L. Esse fator fica na receita, associado a unidade de compra; se essa
unidade mudar, a conversao fica pendente novamente. Confira a capacidade quando
a apresentacao do fornecedor mudar. Nao se presume equivalencia entre massa e
volume. O servidor resolve os nomes e precos pelos IDs ativos do cadastro.

Formulas antigas sao preservadas. Itens sem vinculo ao cadastro ou cujo produto
foi inativado aparecem para revisao. E necessario selecionar seus produtos e
informar a dose de xarope antes de salvar novamente. Nao se atribuem ingredientes
ou doses automaticamente. Revise tambem eventuais ingredientes antigos que
passaram a compor a base para evitar contabiliza-los duas vezes.

## Calculo

- Custo da receita de xarope = soma de quantidade * preco de seus ingredientes.
- Custo por litro de xarope = custo da receita / rendimento informado.
- Custo do xarope usado pelo produto = custo por litro * dose de xarope.
- Custo de 1000 litros de bebida = custo do xarope + custo dos itens adicionais.
- Custo por litro de bebida = total / 1000.
- Custo por garrafa = total * volume_ml / 1000000.

Exemplo: xarope custa R$ 200,00 para render 100 L (R$ 2,00/L). Um produto que
usa 200 L de xarope por 1000 L de bebida e R$ 50,00 de concentrado custa
R$ 450,00 por 1000 L, R$ 0,45/L ou R$ 0,90 por garrafa de 2 L. Uma dose de
100 L com os mesmos adicionais custa R$ 250,00 por 1000 L.

Estimativa teorica, sem perdas, considerando apenas os itens informados.
Sem compra vinculada, ultima compra com preco zero, conversao ausente, base
nao cadastrada, dose ausente ou vinculo invalido deixam o custo pendente. A
receita pode ser salva com preco pendente, sem mostrar total parcial como custo
completo. Frete, impostos, perdas e outras despesas so integram a estimativa se
representados nos itens; nao ha rateio adicional sobre o valor unitario da nota.

## Dados, API e acesso

- `GET /api/custo-produto`: `produtos` PET/GFA, `insumos` do cadastro ativo,
  `xarope` com ingredientes/rendimento/custos/revisao, e `base_litros=1000`.
- `PUT /api/custo-produto/xarope`: `rendimento_litros`, `revisao` e `itens`.
  Retorna a mesma estrutura do GET, com os custos dos produtos recalculados.
- `PUT /api/custo-produto/<produto_id>`: `volume_ml`, `xarope_litros`,
  `xarope_revisao`, `revisao` e `itens`. Retorna a formula e seus custos.
- Cada item recebe `produto_id`, `unidade`, `quantidade` e, se necessario,
  `fator_compra` e `unidade_compra`. `preco_unitario` e calculado na resposta,
  com `compra` (origem, codigo/descricao XML, vinculo e conversao do estoque) e `pendencia_preco`; preco enviado pelo cliente nao e utilizado.
  O nome e validado/resolvido no servidor. IDs inativos/inexistentes, itens
  duplicados e unidades diferentes de kg/g/l/ml/un sao recusados.
- `custo_produto_formulas` preserva formulas existentes e ganha a coluna nullable
  `xarope_litros`. `custo_produto_xarope` armazena uma unica base, inicialmente
  vazia (revisao 0), sem criar ingredientes ou receitas ficticias. Startup
  idempotente, sem alteracao de saldos, restore ou sincronizacao de bancos.
- Gravacoes sao transacionais, com bloqueio da base e revisoes otimistas. Mudanca
  concorrente da formula ou do xarope retorna 409 e preserva o rascunho na tela.
  Erro de gravacao reverte a transacao; produto acabado indisponivel retorna 404.
- Base exige 1 a 100 ingredientes; produto aceita 0 a 100 adicionais. Quantidade e fator de embalagem
  positivos, ate 999999999.999999 (seis casas). Volume,
  rendimento e dose positivos ate 1000000, com tres casas. Numeros nao finitos
  sao recusados. Backend usa Decimal e arredonda somente a apresentacao.

O recurso permanece `riob:custo_produto`, agora identificado no catalogo como
**Custo do produto, xarope e precos do XML**. Ambos os manifests e Config > Usuarios e
acessos usam a mesma chave. As APIs de consulta, produto e xarope exigem esse
recurso, admin ou acesso integral ao modulo. Bloqueios individuais do menu
continuam valendo. Nao ha ampliacao automatica de permissoes nem necessidade de
liberar alteracoes no cadastro de estoque para selecionar ingredientes.
Login/sessao continuam no portal; Render permanece somente leitura.

## Dashboard atual e mensal

DASHBOARD > RioB > Custo do produto abre `/apps/riob#custoProdutoDashboard`.
Mostra o custo atual por garrafa, a tabela mensal por sabor/produto, pendencias,
filtros de ano/linha/produto e grafico mensal do produto selecionado.

`GET /api/custo-produto/dashboard?ano=2026` retorna `data_referencia`, `meses`,
`metodologia` e `produtos` com `atual`, `mensal` e `pendencias`. Ano permitido:
2000 ate o atual; meses futuros nao aparecem. O custo atual usa as compras ate
hoje, mesmo quando o filtro seleciona outro ano.

**Cada mes calcula a formula atual com o ultimo preco de compra disponivel ate
o fechamento daquele mes.** No mes atual, o limite e hoje. Quando nao ha nova
compra no mes, continua valendo a ultima anterior. Antes da primeira referencia
completa, o resultado fica pendente, sem inventar preco zero. A serie compara o
efeito dos precos sobre a receita atual; nao e um registro das receitas
historicamente produzidas. Alteracoes da receita, dose ou conversao recalculam
toda a comparacao; nao se armazenam snapshots mensais de formulas.

O dashboard tem recurso proprio **`riob:custo_produto_dashboard`**, identificado
como Dashboard de custo do produto (consulta), nos dois perfis do manifest e
em Config > Usuarios e acessos. O proxy e a API validam esse acesso e bloqueios
individuais. Consulta nao autoriza editar receitas, e `custo_produto` nao libera
o dashboard automaticamente. Admin e acesso integral continuam abrangendo ambos.

## Testes

- `apps/riob/source/tests/test_custo_produto.py`: cadastro ativo, formulas legadas,
  doses diferentes, ultima compra, mapeamento apos renomeacao, venda a ordem,
  TON/kg e saco/kg, isolamento entre fornecedores, corte mensal, precisao, conflitos,
  rollback, autorizacao e persistencia em banco sintetico.
- `tests/test_custo_produto_access.py`: recurso e escolha individual no proxy,
  incluindo xarope e dashboard com permissao independente, nos perfis Rio Branco/Nanotech e bloqueio cloud.
- `tests/check_custo_produto.py`: navegador com a API real do modulo sobre dados
  sinteticos, selecao de ingredientes, xarope, dose, salvar/reabrir, recusto,
  conversao de bombona, conflito, dashboard mensal e celular. Nenhum teste cadastra receitas no banco operacional.

## Atalho visivel com tela em branco

O portal monta `apps/` do checkout e pode exibir um novo item do manifest antes
que a imagem do backend RioB seja reconstruida. O frontend e os modulos Python
do RioB ficam na imagem: quando ela ainda nao contem `custo_produto.js` e a secao
`custoProduto`, o atalho existe, mas nao ha tela para ativar.

No ambiente local, aplique `./up.sh` pela raiz e valide tanto o portal quanto
RioB: a resposta de `/apps/riob/embed` deve conter `id="custoProduto"`, o asset
`/apps/riob/custo_produto.js` deve responder 200 e a consulta autorizada
`/apps/riob/api/custo-produto` deve retornar a lista. Confira ainda o clique no
menu dentro do shell com iframe. Em producao remota, envie o codigo antes de
executar `./update.sh`. Recarregar o navegador nao substitui a reconstrucao.
O recurso permanece `riob:custo_produto`, com as mesmas restricoes e sem novas
concessoes de acesso.

## Custo completo do dia

O dashboard agora abre a consulta diaria por grupo. O seletor Evolucao mensal
da formula preserva a comparacao anterior. Producao real, pessoal, despesas e
faltas de inventario sao tratados em [Custo diario](CUSTO_DIARIO.md), com recurso
proprio de lancamento `custo_diario` e consulta `custo_produto_dashboard`.
