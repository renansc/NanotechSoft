# Rotas e recursos complementares

Revisao em 2026-07-30.

Este inventario complementa `API_E_DADOS.md` com superficies ativas que antes
nao estavam citadas nominalmente na documentacao. As implementacoes ficam em
`server.py` ou nos blueprints de `legacy_services.py`.

## Fretes, XML de saida e logistica

- `POST /api/fretes/importar-xml-saidas-white-river`
- `GET /api/estoque/importacoes-xml/fretes`
- `GET /api/fretes/<id>/xml-pendentes`
  - lists and filters outgoing XMLs by persisted link, suggestion and search;
    legacy links remain visible by `nota_key`, access key or note number even
    when the current importer source is unavailable or marked for maintenance
- `POST /api/fretes/<id>/xml-pendentes/vincular`
  - links an XML or, with `transferir=true`, moves its single definitive link
    from another frete to the active frete selected in the Kanban
- `POST /api/fretes/<id>/xml-pendentes/desvincular`
  - removes the definitive/pre-link and leaves the NF-e in the visible
    `desvinculado`/`sem_vinculo` pool; automatic preparation must respect this
    manual decision and must not recreate a card until an explicit new link
- `GET /api/fretes/<id>/notas-saida`
  - returns definitive and pending outgoing notes; the UI offers moving either
    kind to another non-archived frete returned by the active-fretes endpoint
- `GET /api/estoque/importacoes-xml/detalhe`
- `PUT /api/estoque/importacoes-xml/logistica`
- `POST /api/estoque/importacoes-xml/classificacao-regras`
- `DELETE /api/estoque/importacoes-xml/classificacao-regras/<regra_id>`

Regras atuais:

- NF-e de saida da mesma cidade reutilizam um card ativo.
- Cidades de uma rota em `cargas_rotas` reutilizam um card mesmo sem veiculo.
- Arquivar um frete com varias cidades cria ou amplia a rota.
- Cards atribuidos a veiculos diferentes nao sao fundidos automaticamente.
- KM, peso e entregas vazios herdam valores do veiculo, carga e XMLs.

## Estoque, lotes e rastreabilidade

- `PUT|DELETE /api/estoque/<movimento_id>`
- `GET /api/estoque/posicao`
- `GET /api/dashboard_estoque`
- `GET /api/estoque/relatorio-comprometido`
- `GET /api/estoque/relatorio-comprometido/pdf`
- `GET /api/estoque/lotes`
- `GET /api/estoque/lotes/<lote_codigo>`
- `GET /api/estoque/rastreabilidade/lotes`
- `POST /api/estoque/rastreabilidade/verificar`
- `PUT /api/estoque/rastreabilidade/vinculos/<vinculo_id>`
- `GET /api/estoque/rastreabilidade/lote`
- `PUT|DELETE /api/estoque/produtos/<produto_id>`
- `POST /api/estoque/produtos/<produto_id>/ajuste`
- `GET|POST /api/estoque/grupos`
- `PUT|DELETE /api/estoque/grupos/<grupo_id>`
- `GET /api/estoque/conferencias/<conferencia_id>`
- `POST /api/estoque/conferencias/<conferencia_id>/confirmar`
- `POST /api/estoque/nfe/preview_fabrica`
- `POST /api/estoque/nfe/direcionar`
- `POST /api/estoque/nfe/direcionar/lote`

Esses endpoints cobrem ajustes auditados, posicao por produto, grupos dinamicos
do dashboard, consulta de lote, rastreabilidade, conferencia e direcionamento
para estoque/manutencao. A exclusao de produto e logica e preserva seus
movimentos; o dashboard considera somente cadastros ativos.

## OCR e leitura assistida

- `POST /api/abastecimentos/ocr_preview`
- `POST /api/abastecimentos/barcode_preview`
- `POST /api/manutencoes/ocr_preview`

Os previews sao editaveis e exigem confirmacao do operador.

## Pontos de venda

- `GET|POST /api/pontos_venda`
- `PUT|DELETE /api/pontos_venda/<item_id>`
- `POST /api/pontos_venda/importar_csv`
- `GET /api/pontos_venda/relatorio`

O recurso mantem agenda e periodicidade de visitas, vendedor, cliente e rota.

## Vendas e caches

- `GET /api/vendas/diario`: consulta os pedidos diarios importados, opcionalmente por `?data=AAAA-MM-DD`.
- `GET /api/vendas/diario/dashboard`: consolida status, positivacao, volume e valor diario por vendedor.
- `GET /api/vendas/diario/kanban`: retorna os cards persistidos com clientes,
  produtos, sugestao de baixa e a etapa de evidencia atual: venda TXT, carga PDF
  ou SELLOUT confirmado.
- O Kanban diario cria e lista cards somente para vendedores com pelo menos um pedido positivo; vendedores com apenas pedidos negativos permanecem no relatorio, mas nao geram card de frete.
- `PUT /api/vendas/diario/kanban/<id>/status`: move o card entre `importado`, `conferir_estoque` e `conferido`; nenhum desses status altera o estoque automaticamente.
- `PUT /api/vendas/diario/kanban/<id>` e `DELETE /api/vendas/diario/kanban/<id>`: salvam o rascunho editavel ou ocultam o card ainda nao vinculado.
- `POST /api/vendas/diario/kanban/<id>/enviar-frete`: valida cidade, caminhao, motorista e entregador, cria um frete `liberado` no Kanban RioB e vincula o card de origem em uma unica transacao. O envio nao baixa estoque.
- `POST /api/vendas/diario/importar-carga-pdf`: importa o PDF de Carga do Caminhao, reconhece mapa, rota, cidades, peso, entregas, volumes, valores e produtos e cria um card de carga elegivel ao mesmo fluxo de frete.
- `POST /api/vendas/cache/importar`: na tela de importacao diaria, recebe tambem o
  SELLOUT final em CSV ou XLSX. Alem das metricas de vendas, a persistencia
  conserva cliente, rota, mapa, endereco, cidade, motorista e ajudantes para a
  conciliacao operacional.
- `POST /api/vendas/diario/importar-clientes`: importa o cadastro de clientes em
  CSV ou XLSX, normalizando codigo, endereco, cidade, rota e vendedor.
- `POST /api/vendas/diario/importar-rotas`: importa a tabela codigo/descricao de
  rotas em PDF.
- `GET /api/vendas/diario/referencias`: informa as quantidades e os ultimos
  arquivos de clientes e rotas importados.
- O campo de cidade do popup diario usa obrigatoriamente `comissao_cidades.id`, sincronizado com as cidades e rotas do Kanban RioB. O texto original do TXT/PDF e apenas referencia e nunca e enviado diretamente ao frete.
- `POST /api/vendas/diario/importar`: dispara a varredura idempotente da pasta ou aceita um TXT manual no campo multipart `arquivo`.
- O compartilhamento SMB deve estar efetivamente montado no host e ser exposto
  ao container em `/imports/vendas-diario`; a existencia de uma pasta local
  vazia no mesmo caminho nao e considerada uma fonte valida pelo deploy.
- A rotina automatica roda imediatamente quando o app inicia dentro da janela
  configurada e repete a varredura idempotente a cada 15 minutos entre 07:10 e
  17:00 por padrao. A janela e controlada por
  `RB_VENDAS_DIARIO_JANELA_INICIO`, `RB_VENDAS_DIARIO_JANELA_FIM` e
  `RB_VENDAS_DIARIO_INTERVALO_MINUTOS`; `RB_VENDAS_DIARIO_HORA` permanece como
  fallback compativel para o inicio da janela. O container RioB usa
  `TZ=America/Sao_Paulo` para interpretar essa janela no horario da operacao.
  Entre as passagens, um snapshot de nome, tamanho e modificacao evita reler os
  PDFs antigos quando nenhuma fonte mudou.

- `GET /api/vendas/relatorio/preco-medio/pdf`
- `GET /api/vendas/dashboard`
- `GET /api/dashboard_vendas`
- `POST /api/vendas/cache/processar`
- `PUT /api/vendas/cache/<cache_id>/ativar`
- `DELETE /api/vendas/cache/<cache_id>`

O cache e processado no backend; ativacao e exclusao afetam somente a base
selecionada para os relatorios.

## Edicao e exclusao de comissoes

- `PUT|PATCH|DELETE /api/comissao/lancamentos/<item_id>`
- `DELETE /api/comissao/cadastros/<item_id>`
- `DELETE /api/comissao/cidades/<item_id>`

As exclusoes passam pelas validacoes e trilhas de auditoria do backend.

## Escala, cargas e rotas

- `GET|POST /api/escala/pdf`
- `GET|POST /api/escala/sorteio-regras`
- `DELETE /api/escala/sorteio-regras/<regra_id>`
- `POST /api/cargas/importar_pdf`
- `GET|POST /api/cargas/rotas`
- `PUT|DELETE /api/cargas/rotas/<rota_id>`

`cargas_rotas` e o cadastro canonico de grupos de cidades e tambem recebe as
rotas aprendidas ao arquivar fretes.

## Abastecimentos e manutencao

- `PUT /api/abastecimentos/<abastecimento_id>/abastecer`
- `PUT|DELETE /api/abastecimentos/<abastecimento_id>`
- `POST /api/abastecimentos/<abastecimento_id>/importar_nfe`
- `POST /api/abastecimentos/<abastecimento_id>/importar_nfe_dfe`
- `GET /api/abastecimentos/<abastecimento_id>/pdf`
- `GET /api/manutencoes/importacoes-xml`
- `POST /api/manutencoes/importacoes-xml/<pre_lancamento_id>/descartar`
- `POST /api/manutencoes/importacoes-xml/devolver-estoque`

O pre-lancamento permite revisar, descartar ou devolver a NF-e ao estoque.

## Identidade, chat, agente e arquivos

- `GET /api/me`
- `GET /api/chat/mensagens/<mensagem_id>/anexo`
- `GET /api/devolucoes/fotos/<filename>`
- `POST /api/agent/chat`
- `GET /docs/<filename>`

`/api/me` recebe a identidade do portal; o RioB continua sem login proprio.

## Monitores e blueprints legados

- `/monitor/esxi/<subpath>`
- `/monitor/cameras/<subpath>`
- `/monitor/automacao/<subpath>`
- `POST /importar-com-progresso`
- `GET /status-importacao/<job_id>`
- `GET /status-importacao`
- `GET /estoque/exportar`
- `GET /abastecimentos/exportar`
- `GET|POST /fornecedores`
- `POST /importar-historico-xml`
- `POST /recuperar-conteudo`
- `GET /emails`
- `GET /email/<email_id>`
- `GET /anexos`
- `GET /download/<attachment_id>`

As rotas sem `/api` sao entradas externas dos blueprints legados. Os monitores
sao proxies HTTP para apps auxiliares.

## Criterio para limpeza de codigo

Uma funcao so pode ser removida quando nao tiver referencia no Python,
JavaScript, HTML ou testes e nao for rota, callback, handler de protocolo,
override de biblioteca ou entrada publica de integracao. Metodos de
`HTMLParser`, `BaseHTTPRequestHandler` e funcoes decoradas pelo Flask continuam
validos mesmo sem chamada textual direta.
### Composicao de cards Vendas Diario (TXT, PDF e XML)

- PDF exige `vendedor_codigo` no upload; TXT conserva o vendedor do arquivo.
- `POST /api/vendas/diario/kanban/<card_id>/unir` move uma origem ou um card
  composto para outro card ativo da mesma data. Caminhoes divergentes bloqueiam
  a operacao.
- `POST /api/vendas/diario/kanban/<card_id>/separar` devolve uma origem a um card
  independente.
- Toda uniao/separacao e registrada em `vendas_diario_kanban_historico`.
- Cidade/rota, mapa e data geram sugestoes. A uniao e automatica somente para
  um par unico TXT/PDF confirmado no SELLOUT por mesma data, vendedor, cidade,
  mapa final unico e sufixo equivalente do mapa; ambiguidades continuam manuais.
- TXT, PDF e XML sao evidencias alternativas da carga. A sugestao de baixa nao
  soma fontes convergentes: XML oficial tem prioridade, depois TXT e por ultimo
  PDF. A baixa efetiva continua dependendo da conferencia de estoque existente.
- O fluxo de validacao possui tres estados independentes do status operacional
  do card: `1. Venda TXT recebida`, `2. Carga PDF formada` e `3. SELLOUT
  confirmado`.
- O SELLOUT e a fonte final. O vinculo usa primeiro o numero do mapa; quando o
  PDF ainda nao existe, usa data do pedido e vendedor. Valor e quantidade de
  clientes do TXT continuam visiveis ao lado do final, e qualquer alteracao e
  apresentada como divergencia em vez de sobrescrever a evidencia anterior.
- A rotina fica no menu `Import -> Importar SELLOUT`, que concentra SELLOUT,
  cadastro de clientes e tabela de rotas.
- Cadastro de clientes e tabela de rotas enriquecem o resultado final com
  endereco estruturado, cidade e descricao oficial da rota. Motorista e
  ajudantes vem do proprio SELLOUT quando preenchidos; o sistema nao inventa
  equipe quando o arquivo traz `000-` ou campo vazio. O prefixo do mapa sugere
  o caminhao quando existe veiculo com o mesmo numero no cadastro.
