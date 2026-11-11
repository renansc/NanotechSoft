# Custo do produto, xarope base e xaropes compostos

GESTAO > RioB > Custo do produto abre `/apps/riob#custoProduto`. O cadastro
central `estoque_produtos` fornece tanto os produtos acabados ativos AGUA/PET/GFA
quanto os ingredientes selecionaveis. Nao existe cadastro paralelo de itens.

## Uso

1. Abra **Cadastrar / editar base de xarope**. Selecione os ingredientes do
   cadastro existente, informe quantidades, unidades e o rendimento da receita
   em litros de xarope base.
2. Use **Criar xarope composto por sabor**. Informe o sabor, quantos litros da
   base entram no lote, quantos litros de bebida pronta o lote produz e os ingredientes adicionais
   (concentrado, aroma etc.). O mesmo composto atende PET, retornavel e volumes
   diferentes.
   A proporcao por 1000 L e derivada automaticamente. Exemplo: 500 L de base
   em um lote que produz 3750 L de bebida equivalem a 133,333 L de base/1000 L;
   todos os ingredientes do lote usam o mesmo fator `1000 / 3750`.
3. Abra a formula do produto e selecione o sabor. O rendimento da bebida e
   herdado da receita; o volume da embalagem determina automaticamente sua
   parcela entre PET, retornavel, 2 L, 600 ml ou 200 ml.
4. Confira o volume e a quantidade de garrafas por pacote/caixa. Cadastre apenas
   itens da apresentacao (PET/garrafa, tampa, rotulo etc.), alem de agua quente
   quando houver. Nao repita itens do composto. As quantidades da apresentacao
   sao por **uma garrafa pronta**: normalmente 1 PET/garrafa, 1 tampa e 1 rotulo.
   O sistema converte automaticamente esse custo para 1000 L conforme o volume.
5. Salve. Alterar base, composto ou compra recalcula todas as apresentacoes
   vinculadas.

Agua acabada usa o mesmo cadastro de formula para embalagem, tampa, agua quente
e rateio, mas nao exige nem cobra xarope base/composto.

Em **Config > Rateio de custos de producao**, cadastre mao de obra, impostos,
energia, caldeira/lenha, combustivel, agua e outros custos indiretos. Cada linha aceita uma
destas bases:

- valor mensal em reais, dividido pelo volume mensal de referencia e convertido
  em custo por litro;
- valor direto em R$/L;
- valor por hora em R$/h, dividido pela capacidade produtiva informada em L/h;
- valor mensal distribuido nas horas trabalhadas e depois dividido pela
  capacidade produtiva em L/h;
- abastecimentos concluidos do mes mais recente com lancamentos, somados
  automaticamente e divididos pelo volume mensal de producao;
- percentual sobre o custo direto de xarope, itens da apresentacao e agua quente.

Para a caldeira, informe a capacidade produtiva da linha em litros por hora e o
custo do consumo de lenha por hora. Exemplo: R$ 250/h para 2.500 L/h equivale a
R$ 0,10/L. A capacidade e obrigatoria quando existir qualquer linha por hora.
Para combustivel com valor mensal, use `mensal_horas`: com 44 h/semana, o
sistema considera `44 * 52 / 12 = 190,667 h/mes`, calcula o custo horario e o
divide pela capacidade em L/h. As horas semanais sao configuraveis e iniciam em 44.
Para reaproveitar o que ja foi lancado em Frota > Abastecimentos, use
`abastecimentos`. Entram todas as linhas com status `abastecido` e valor positivo
do ultimo mes que possua registros; linhas apenas liberadas ficam fora. A tela
mostra o periodo, quantidade de registros, litros abastecidos, valor total e o
custo resultante por litro produzido. Isso evita somar todo o historico contra
apenas um mes de producao e mantem o custo no periodo mais recente disponivel.

O rateio e uma configuracao padrao atual, compartilhada por todas as
apresentacoes. Ele nao substitui o lancamento de gastos reais em Custos diarios
por grupo. Ao analisar o custo real do dia, nao repita a mesma despesa nas duas
origens.

A selecao mostra nome e ID do cadastro. O seletor tambem identifica a
nota/preco disponivel ou avisa `sem NF-e de entrada vinculada`, ajudando a
distinguir cadastros semelhantes. Preformas sao identificadas visualmente pela
regra operacional: faixa 40 para PET 2 L, faixa 20 para PET 600 ml e faixa 15
para PET 200 ml. Quando existe uma **referencia fiscal de fornecedor** utilizavel,
o preco usado no calculo e automatico e somente leitura: usa o valor unitario da
ultima compra pela data de emissao, ate a data atual no fuso America/Sao_Paulo.
As fontes sao NF-e/XML confirmada no estoque e o resumo C170 de entrada
sincronizado pelo SPED Fiscal. Na mesma data, a NF-e confirmada tem prioridade.
A tela identifica fonte, numero, data e unidade. Quando ainda nao existe uma
referencia utilizavel, o proprio campo `Preco usado` fica
digitavel; o numero informado e sincronizado e persistido como
`preco_provisorio` em R$ por kg, g, L, ml ou unidade escolhida no item. Esse
valor e identificado
como provisorio e substituido automaticamente no calculo quando uma referencia valida
passa a existir. O valor provisorio permanece salvo para os cortes mensais
anteriores a compra; `preco_unitario` antigo ou enviado pelo navegador continua
ignorado. O campo provisorio permanece digitavel mesmo com NF-e; nessa situacao
a NF-e apenas tem prioridade no calculo e a digitacao nao e apagada.

A fonte principal e `importar_xml_estoque_itens`, com `ENTRADA_ESTOQUE` e
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

O complemento SPED fica em `custo_produto_sped_itens`. Ao importar um TXT no
app SPED, o arquivo integral continua local no navegador e somente o resumo dos
itens C170 de entrada e enviado ao endpoint `POST /api/custo-produto/sped`.
Cada nova importacao substitui atomicamente o resumo da mesma empresa e periodo.
Saidas, transferencias, devolucoes e bonificacoes sao descartadas. O vinculo usa
fornecedor/codigo ja confirmado pelo estoque, alias `nfe_entrada` e assinatura
codigo/descricao confirmada. Quando esses vinculos de XML nao existem, o campo
`descricao_sped` de **Cadastros > Produtos** tem prioridade: o operador copia a
descricao do registro 0200/C170 como ela aparece no SPED, e o sistema exige uma
correspondencia exata apos normalizar maiusculas, acentos e espacos. A mesma
descricao nao pode ser salva em dois produtos ativos. Exemplo:
`Concentrado liquido para ref. framboesa` pode cadastrar
`CONCENTRADO P/REFRI FRAMBOESA BD25 C/C`. Somente produtos antigos sem esse
campo continuam usando, como contingencia, nome exato ou descricao fortemente
compativel e nao ambigua. Assim, `Aroma Natural Laranja Especial` ainda pode
aproveitar `LARANJA AROMA NATURAL DE` durante a transicao.
O valor unitario SPED e
`(VL_ITEM - VL_DESC) / QTD`. A sincronizacao exige simultaneamente acesso a
Importacao do SPED e `riob:custo_produto`; nao concede permissoes automaticamente.
O parser resolve o codigo de unidade do C170 pelo registro 0190 antes de enviar
o resumo. Um fator de conversao informado antes da primeira referencia fiscal
passa a usar a unidade encontrada quando o vinculo aparece.
Cadastros manuais formados por um unico nome tecnico distintivo tambem podem
usar uma descricao fiscal mais longa quando essa palavra aparece inteira e
identifica somente um produto ativo. Exemplo: `DIATOMITA` reconhece
`DIATOMITA CA 500`; a unidade historica `22` do EFD e tratada como saco (`SC`).
Como o C170 da NF 75506 informa quantidade de sacos, mas nao o peso de cada
saco, a tela solicita o fracionamento real em kg/SC antes de calcular o custo.
Rotulos fiscais truncados podem usar a largura unica (`33,5` cm para 2 L, `23`
cm para 600 ml e `16,6` cm para 200 ml) junto do sabor. Preformas usam cor e
faixa de peso somente quando a combinacao identifica um unico cadastro: 14-18 g
para 200 ml, 20-30 g para 600 ml e 38-50 g para 2 L. O codigo EFD historico
`68` e normalizado como milheiro.

Para produtos acabados PET sem formula, a consulta oferece **Autocompletar pelo
mesmo sabor** quando existe outra apresentacao ja cadastrada. A sugestao reutiliza
o mesmo xarope composto, conserva a tampa e procura preforma da mesma cor e
rotulo do mesmo sabor no volume de destino (200 ml, 600 ml ou 2 L). A associacao
so aparece quando cada troca e unica; ambiguidades ficam para cadastro manual.
A sugestao abre no editor e nao grava sozinha: o operador confere os itens e
salva, preservando revisao otimista, autorizacao e historico de atualizacao.

Uma formula cadastrada pode ser removida por **Excluir formula**. A confirmacao
remove somente a composicao de custo daquela apresentacao: produto, saldo de
estoque, NF-e e SPED permanecem intactos. O item volta para **Sem formula**, sai
do dashboard de custos e pode receber uma nova formula ou autocomplete quando a
apresentacao voltar a ser produzida. A exclusao exige a revisao atual e retorna
conflito se outra pessoa tiver alterado a formula antes da confirmacao.

Produtos de outras marcas ou que nao pertencem a producao podem ser retirados
por **Remover da lista**. Essa acao nao desativa nem apaga o produto do estoque,
nao altera saldo, formula ou referencias NF-e/SPED; apenas o oculta da lista e do
dashboard de custo de producao. Marque **Mostrar itens removidos** para consultar
esses produtos e use **Restaurar na lista** se passarem a ser produzidos no futuro.

Na carga inicial das formulas PET Rio Branco, o Abacaxi 2 L serve apenas como
referencia estrutural. Cada SKU e amarrado explicitamente ao seu xarope composto,
tampa, preforma e rotulo do sabor e do volume; nao existe copia generica entre
sabores. Apresentacoes sem SKU ou embalagem cadastrada permanecem fora ate que o
cadastro fiscal correspondente exista.

Conversoes tonelada (T/TO/TON)/kg/g, l/ml e milheiro/unidade sao automaticas.
Nos SPED antigos da Rio Branco, os codigos `28` e `429` do registro `0190`
representam milheiro e sao convertidos em 1.000 rotulos. Um item cadastrado como
rotulo, tampa ou preforma somente aceita referencia fiscal com o mesmo tipo de
embalagem; isso impede confundir o produto acabado `PET 12X200ML` com seu rotulo.
Quando codigo e descricao do fornecedor diferem do cadastro, um rotulo fiscal
tambem pode ser vinculado pela combinacao unica de sabor e volume; duplicidades
de cadastro continuam pendentes para revisao, sem escolha automatica.
Se uma futura nota vier em metro (`M`, `MT` ou `MTS`), o primeiro valor da
dimensao do rotulo e tratado como passo em centimetros: `100 / 33,5` rotulos por
metro no 2 L, `100 / 23` no 600 ml e `100 / 16,6` no 200 ml. Essa conversao e
uma estimativa geometrica; notas em milheiro continuam exatas e prioritarias.
Quando um XML de tampa, rotulo, preforma, garrafa ou rolha usa `ML` como
abreviacao de milheiro, a descricao de peca elimina a ambiguidade com
mililitro e o sistema aplica 1.000 unidades.
Assim, uma preforma faturada a R$ 526,50/MIL custa R$ 0,5265 por unidade,
R$ 3,1590 em um pacote com seis garrafas e R$ 263,25 para as 500 garrafas que
formam 1.000 L na apresentacao de 2 L. Uma caixa fisica de 8.352 unidades a
esse valor por milheiro equivale a R$ 4.397,33; R$ 526,50 nao e o valor da caixa.
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
foi inativado aparecem para revisao. E necessario vincular uma receita de sabor
com rendimento de bebida valido antes de salvar novamente. Nenhum sabor e inferido ou migrado
automaticamente; as receitas legadas permanecem armazenadas para revisao.

## Calculo

- Custo do xarope base = soma de quantidade * preco de seus ingredientes.
- Custo do lote do sabor = custo por litro da base * litros de base usados + itens do sabor.
- Custo dos xaropes por litro de bebida = custo do lote / litros de bebida produzidos.
- O dashboard separa ingredientes do sabor por litro de bebida e sabor + base
  por litro de bebida. O card da base mostra R$/L de xarope puro, portanto os
  valores nao devem ser comparados sem considerar a diluicao da bebida pronta.
- Custo dos xaropes por 1000 L de bebida = custo do lote * 1000 / litros de bebida produzidos.
- Custo da agua quente = quantidade em litros * valor por litro.
- Embalagem por garrafa = soma de quantidade por garrafa * preco unitario de
  PET/garrafa, tampa, rotulo e demais itens da apresentacao.
- Unidades em 1000 L = 1000000 / volume_ml.
- Embalagem por 1000 L = embalagem por garrafa * unidades em 1000 L.
- Custo direto de 1000 litros = xarope + embalagem por 1000 L + agua quente.
- Custos mensais = valor mensal / volume mensal de referencia * 1000.
- Custos por litro = valor por litro * 1000.
- Custos por hora = valor por hora / capacidade produtiva em L/h * 1000.
- Combustivel mensal por horas = valor mensal / (`horas_semanais * 52 / 12`) /
  capacidade produtiva em L/h * 1000.
- Combustivel lancado = soma dos abastecimentos concluidos no mes mais recente /
  volume mensal de producao * 1000.
- Custos percentuais = custo direto * percentual / 100.
- Custo de 1000 litros de bebida = custo direto + mao de obra + impostos +
  energia + caldeira/lenha + agua rateada + outros custos.
- Custo por litro de bebida = total / 1000.
- Custo por garrafa = liquido e rateio proporcionais ao volume + uma embalagem.
- Custo por pacote = custo por garrafa * garrafas por pacote.

A resposta e as telas mostram os dois cortes: custo direto **sem rateio** e
custo total **com rateio**, por 1000 L, litro, garrafa e pacote. Isso evita
confundir o custo dos insumos da formula com os custos compartilhados.

Exemplo: a base custa R$ 2,00/L. A receita de limao usa 500 L da base
(R$ 1.000,00) e R$ 500,00 de ingredientes, produzindo 3.750 L de bebida. O lote
custa R$ 1.500,00; portanto os xaropes custam R$ 400,00 por 1.000 L de bebida.
Uma garrafa de 2 L recebe R$ 0,80 desse custo antes de embalagem e rateio.
Se a unidade usar 1 PET de R$ 0,40, 1 tampa de R$ 0,05 e 1 rotulo de R$ 0,02,
a embalagem acrescenta R$ 0,47 por garrafa, e nao R$ 0,47 por 1000 L.

Estimativa teorica, sem perdas, considerando os itens e rateios informados.
Sem compra vinculada nem valor provisorio, ultima compra com preco zero sem
valor provisorio, conversao ausente sem valor provisorio, base nao cadastrada,
rendimento de bebida ausente ou vinculo invalido deixam o custo pendente. A
receita pode ser salva com preco pendente, sem mostrar total parcial como custo
completo. Perdas e fretes so integram a estimativa quando cadastrados nos itens
ou em Outros no rateio; o valor unitario da NF-e nao e alterado.

## Dados, API e acesso

- `GET /api/custo-produto`: `produtos` AGUA/PET/GFA, `insumos`, `xarope` base,
  `xaropes_compostos`, `rateio` e `base_litros=1000`.
- `GET/PUT /api/custo-produto/rateio`: le/salva `volume_mensal_litros`,
  `capacidade_litros_hora`, `horas_semanais`, `revisao` e ate 100 itens com `descricao`,
  `categoria` (`mao_obra`, `impostos`, `energia`, `caldeira`, `combustivel`, `agua`,
  `outros`), `tipo` (`mensal`, `mensal_horas`, `abastecimentos`, `hora`, `litro`,
  `percentual`) e `valor`. Em `abastecimentos`, o valor e calculado e retornado
  com `periodo_referencia`, `registros_origem` e `litros_combustivel`.
  Em linhas `hora`, `valor` e R$/h e a capacidade deve ser positiva.
- `PUT /api/custo-produto/xarope`: `rendimento_litros`, `revisao` e `itens`.
  Retorna a mesma estrutura do GET, com os custos dos produtos recalculados.
- `POST /api/custo-produto/xaropes-compostos` cria um sabor; `PUT
  /api/custo-produto/xaropes-compostos/<id>` o altera. Recebem `nome`,
  `xarope_base_litros`, `rendimento_litros` (litros de bebida pronta produzidos),
  `itens`, `revisao` e `xarope_revisao`, e retornam o snapshot recalculado.
  `dose_litros_1000` e coluna/campo legado: a entrada do cliente e ignorada e
  a resposta expoe a proporcao derivada tambem em `xarope_base_litros_1000`.
- `PUT /api/custo-produto/<produto_id>`: `volume_ml`, `unidades_pacote`, `xarope_composto_id`,
  `xarope_composto_revisao`, `agua_quente_litros`,
  `agua_quente_valor_litro`, `revisao` e `itens`. Os dois campos de agua quente sao opcionais em conjunto; se um for
  informado, o outro e obrigatorio. AGUA ignora campos de xarope; PET/GFA exigem
  composto valido. Retorna a formula e seus custos, incluindo
  `calculo.custo_agua_quente`, custos diretos/indiretos, componentes por 1000 L,
  unidade e pacote, `custo_itens_unidade`, `custo_itens_1000_litros` e
  `itens_unidade` com o detalhamento de PET/garrafa, tampa, rotulo e demais
  itens por garrafa, pacote e 1.000 L. Os campos `custo_*_sem_rateio` separam o custo direto dos totais
  `custo_*`, que incluem o rateio.
- `DELETE /api/custo-produto/<produto_id>`: recebe `revisao`, remove somente a
  linha de `custo_produto_formulas` e preserva produto, estoque e referencias
  NF-e/SPED. Formula ausente retorna 404 e revisao desatualizada retorna 409.
- `DELETE /api/custo-produto/produtos/<produto_id>` marca o produto fora da lista
  de producao, e `POST /api/custo-produto/produtos/<produto_id>/restaurar` desfaz
  a marcacao. A tabela `custo_produto_exclusoes` guarda operador e data sem
  modificar `estoque_produtos` ou `custo_produto_formulas`.
- `POST /api/custo-produto/sped` recebe empresa, periodo, arquivo e ate 25.000
  resumos de itens C170. Persiste somente os campos necessarios a referencia de
  custo e substitui o periodo em uma unica transacao. Exige `custo_produto`.
- Cada item recebe `produto_id`, `unidade`, `quantidade` e, se necessario,
  `fator_compra`, `unidade_compra` e `preco_provisorio`. `preco_unitario` e
  calculado na resposta, com `fonte_preco` igual a `nfe`, `sped` ou `provisorio`,
  `compra` (origem, codigo/descricao XML, vinculo e conversao do estoque) e
  `pendencia_preco`; `preco_unitario` enviado pelo cliente nao e utilizado.
  O nome e validado/resolvido no servidor. IDs inativos/inexistentes, itens
  duplicados e unidades diferentes de kg/g/l/ml/un sao recusados.
  Em xarope base e composto, `quantidade` pertence ao lote da receita. Na
  formula do produto acabado, `quantidade` pertence a uma garrafa pronta.
- `custo_produto_formulas` preserva formulas existentes e possui as colunas
  nullable `xarope_litros` legado, `xarope_composto_id`, `agua_quente_litros` e
  `agua_quente_valor_litro`, alem de `unidades_pacote`. `custo_produto_xarope` armazena a unica base e
  `custo_produto_xaropes_compostos` armazena as receitas reutilizaveis por sabor,
  e `custo_produto_rateio` guarda a configuracao unica de custos indiretos, sem
  criar ingredientes ou receitas ficticias. Startup
  idempotente, sem alteracao de saldos, restore ou sincronizacao de bancos.
- Gravacoes sao transacionais, com bloqueio da base/composto e revisoes otimistas.
  Mudanca concorrente da formula ou do composto retorna 409 e preserva o rascunho.
  Erro de gravacao reverte a transacao; produto acabado indisponivel retorna 404.
- Base exige 1 a 100 ingredientes; produto aceita 0 a 100 adicionais. Quantidade e fator de embalagem
  positivos, ate 999999999.999999 (seis casas). Volume,
  e rendimento da bebida positivos ate 1000000, com tres casas. Numeros nao finitos
  sao recusados. Backend usa Decimal e arredonda somente a apresentacao.

O recurso permanece `riob:custo_produto`, agora identificado no catalogo como
**Custo do produto: formulas, exclusao e recadastro de formulas, remocao e restauracao de itens da lista de producao, referencias de preco por NF-e e SPED, vinculo explicito pela descricao SPED do cadastro de produto, autocomplete de apresentacoes PET por sabor, embalagens
por unidade, conversoes, pacotes, valores provisorios, rateios, caldeira por hora
e combustivel por 44 h semanais ou abastecimentos**. GESTAO > Custo do produto e CONFIG > Rateio de
custos de producao usam a mesma chave. Ambos os manifests e Config > Usuarios e
acessos usam a mesma chave. As APIs de consulta, produto e xarope exigem esse
recurso, admin ou acesso integral ao modulo. Bloqueios individuais do menu
continuam valendo. Nao ha ampliacao automatica de permissoes nem necessidade de
liberar alteracoes no cadastro de estoque para selecionar ingredientes.
Login/sessao continuam no portal; Render permanece somente leitura.

## Dashboard atualizado

DASHBOARD > RioB > Custo do produto abre `/apps/riob#custoProdutoDashboard`.
Mostra somente produtos com formula de producao cadastrada. No topo, exibe o
xarope base e os compostos em cards coloridos por sabor, seguidos pelos itens
de rateio. Abaixo, separa Agua, PET e Retornavel por sabor, com custo direto sem
rateio e total com rateio por garrafa e pacote, detalhando PET/garrafa, tampa,
rotulo e demais itens por garrafa, pacote e 1.000 L. Os cards de sabor separam
ingredientes do sabor e composto com base por litro de bebida. Agua usa identidade azul e os
refrigerantes usam a cor do sabor. Nao ha
seletor de data, apuracao diaria, grafico ou serie historica nesta tela.

`GET /api/custo-produto/dashboard` retorna `data_referencia`, `metodologia`,
`xarope_base`, `sabores`, `rateio` e somente `produtos` com formula, cada qual
com `atual` e `pendencias`. O custo usa a formula e o
rateio atuais com a ultima compra fiscal de fornecedor disponivel ate hoje.
Antes da primeira NF-e ou referencia SPED utilizavel, usa o valor provisorio
atual; sem ambos, fica pendente
sem inventar preco zero.

O dashboard tem recurso proprio **`riob:custo_produto_dashboard`**, identificado
como **Consulta de custos em cards de agua, PET e retornavel e relatorio PDF por
sabor com formulas, XML/SPED, notas, unidades, rateios e embalagens**, nos dois perfis do manifest e
em Config > Usuarios e acessos. O proxy e a API validam esse acesso e bloqueios
individuais. Consulta nao autoriza editar receitas, e `custo_produto` nao libera
o dashboard automaticamente. Admin e acesso integral continuam abrangendo ambos.

## Relatorio Custo produto

RELATORIOS > RioB > Custo produto abre
`/apps/riob#relatorios:custo_produto`. O relatorio consome o mesmo
`GET /api/custo-produto/dashboard` usado pelos cards, portanto nao mantem um
segundo calculo nem uma referencia historica paralela. A resposta inclui os
itens ja precificados pelo servidor na base, nos compostos e nas apresentacoes.
O relatorio organiza uma folha por sabor e documenta a conversao dos rateios,
a formacao do lote do xarope base e do composto e o fechamento das apresentacoes
em 1.000 L, litro, unidade e pacote.

Cada ingrediente e embalagem mostra quantidade, unidade da formula, fonte do
preco (`XML / NF-e`, `SPED Fiscal` ou valor provisorio), numero e data da nota,
valor e unidade de compra, fator de conversao, preco unitario aplicado e custo
resultante. Para cada produto, a memoria separa custo direto e indireto, apresenta
os componentes (xarope, embalagens, agua quente, mao de obra, impostos, energia,
caldeira, combustivel, agua e outros) e abre PET/garrafa, tampa, rotulo e demais
itens por unidade, pacote e 1.000 L. Os filtros de linha e produto/sabor definem
as folhas e apresentacoes incluidas. O botao **Gerar / imprimir PDF** usa a
impressao do navegador em A4 paisagem e aplica quebra antes de cada sabor.

O menu reutiliza a permissao somente leitura `custo_produto_dashboard`. Ele nao
concede `custo_produto`, nao permite editar formulas e aparece no catalogo de
Config > Usuarios e acessos nos dois perfis do manifest.

## Testes

- `apps/riob/source/tests/test_custo_produto.py`: cadastro ativo, formulas legadas, exclusao concorrente e recadastro, remocao/restauracao da lista de producao,
  composto compartilhado entre PET/retornavel, agua sem xarope, rendimento da bebida e proporcao automatica,
  valor provisorio com troca automatica pela NF-e, agua quente,
  rateio mensal/por hora/por litro/percentual, conversao da caldeira pela
  capacidade produtiva, uma tampa/PET/rotulo por garrafa, custo com/sem rateio
  por unidade/pacote e auditoria da
  cadeia 1000 L -> ml -> pacote, ultima compra, mapeamento apos renomeacao, venda a ordem,
  sincronizacao C170, substituicao por periodo e prioridade da NF-e em empate,
  TON/kg, ML/milheiro de pecas, caixa de preformas, saco/kg, isolamento entre fornecedores,
  custo atualizado, precisao, conflitos,
  rollback, autorizacao, rastreabilidade fiscal dos itens do relatorio e
  persistencia em banco sintetico.
- `tests/test_custo_produto_access.py`: recurso e escolha individual no proxy,
  incluindo xarope, dashboard e relatorio com permissao independente, nos perfis Rio Branco/Nanotech,
  bloqueio cloud e validacao da sintaxe do JavaScript no navegador.
- `tests/check_custo_produto.py`: navegador com a API real do modulo sobre dados
  sinteticos, base, composto por sabor, campo provisorio digitavel, rendimento, salvar/reabrir, recusto,
  exclusao preservando dados fiscais, remocao e restauracao da lista, conversao de bombona, conflito, dashboard atualizado, memoria do relatorio,
  filtros e celular. Nenhum teste cadastra receitas no banco operacional.

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

Producao real, pessoal, despesas e faltas de inventario continuam tratados em
[Custo diario](CUSTO_DIARIO.md), com recurso proprio `custo_diario`. Essa
apuracao nao aparece no dashboard de custo do produto, que por enquanto mostra
somente o valor padrao mais recente.
