# Importacao TXT/CSV/ODS de manutencao

## Objetivo

A tela Gestao de Frota > Manutencoes aceita notas digitadas ou convertidas por
IA para TXT/CSV ou planilhas ODS. Todo arquivo e tratado somente como dados: textos dentro dele
nao sao executados nem interpretados como instrucoes. A importacao sempre passa
por previa e cria pre-lancamentos; a manutencao definitiva continua exigindo a
conferencia do veiculo e o comando Salvar Manutencao.

## Formatos aceitos

- delimitadores `|`, `;` e tabulacao;
- UTF-8, UTF-8 com BOM, Windows-1252 e Latin-1;
- cabecalhos equivalentes a documento/nota/orcamento, data,
  item/descricao/produto, valor/total e placa/frota/veiculo;
- quatro colunas sem cabecalho (`documento | data | item | valor`) e quinta
  coluna opcional para placa/frota;
- metadado opcional `FORNECEDOR: nome`. Sem ele, a previa sugere o nome pelo
  arquivo e permite edicao.

O padrao ODS aceita as colunas `LOCAL`, `TIPO/AGRUPADO`, `VEICULO`, `DIA`,
`MES`, `DESC`, `VALOR` e `ID`. `LOCAL` vira o fornecedor; linhas com o mesmo
fornecedor, agrupador, data e veiculo formam uma nota. Sem agrupador, cada linha
e um documento individual. `VEICULO` pode conter a placa ou o numero exato da
frota, e `ID` e preservado na observacao do item. A coluna `ANO` e opcional;
quando ausente, o leitor usa o ano dos metadados do ODS e mostra esse fato na
previa para conferencia.

Datas validas usam `dd/mm/aaaa`, `dd-mm-aaaa` ou ISO. Valores aceitam o padrao
brasileiro, inclusive milhares (`R$ 1.660,00`). Linhas do mesmo documento, data
e referencia de veiculo formam uma nota. Linhas repetidas sao preservadas.

## Conferencia e seguranca dos dados

A previa mostra arquivo, numero, data, fornecedor, referencia, veiculo sugerido,
itens, total e alertas. Numero com `?`, texto marcado como pouco legivel,
duplicatas e veiculo ausente nunca sao corrigidos silenciosamente. O operador
pode desmarcar a nota, corrigir o fornecedor e selecionar um veiculo.
Somente placa ou numero de frota com correspondencia exata e preselecionado;
referencias parecidas ficam sem vinculo e geram alerta para revisao manual.

O limite e de 20 arquivos e 2 MB por arquivo, com ate 5.000 linhas. Extensoes
aceitas: `.txt`, `.csv` e `.ods`. O servidor volta a interpretar os arquivos ao
confirmar; nao confia nos valores exibidos no navegador.

A chave idempotente usa documento, data, referencia e itens. Reimportar a mesma
nota atualiza o pre-lancamento pendente, sem criar duplicata. Uma nota ja
confirmada e ignorada. O texto das linhas originais e o nome do arquivo ficam
no historico da manutencao.

## API e autorizacao

- `POST /api/manutencoes/importacoes-txt/preview`: multipart com `arquivos`;
- `POST /api/manutencoes/importacoes-txt`: os mesmos arquivos e `ajustes` JSON;
- `GET /api/manutencoes/importacoes-xml?status=pendente`: fila unificada de
  NF-e/XML e TXT/CSV/ODS;
- `POST /api/manutencoes`: confirma um pre-lancamento no cadastro definitivo.

As duas novas rotas usam o item existente
`/apps/riob#gestaofrota:manutencao`, recurso `frota`. Nao ha concessao
automatica. Notas TXT/CSV/ODS nao podem ser devolvidas ao estoque, porque nao vieram do
fluxo de classificacao de NF-e.

## Persistencia

`manutencao_xml_pre_lancamentos` continua sendo a fila compartilhada e ganhou
`origem_tipo`, `arquivo_origem`, `texto_origem` e `avisos_json`. Registros
antigos assumem origem `xml`. Ao confirmar, `manutencoes.ocr_texto` e
`manutencoes.ocr_origem` recebem o nome do TXT/CSV/ODS para auditoria. A fila
distingue `origem_tipo=ods` das importacoes textuais.

## Testes

- `apps/riob/source/tests/test_manutencao_txt.py`: formatos, moeda, agrupamento,
  ambiguidades, sugestao de veiculo, previa e interface;
- `tests/test_manutencao_txt_access.py`: liberacao e bloqueio individual das
  rotas no proxy do portal.
