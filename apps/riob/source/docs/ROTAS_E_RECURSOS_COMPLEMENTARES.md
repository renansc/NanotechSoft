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
- `GET /api/estoque/lotes`
- `GET /api/estoque/lotes/<lote_codigo>`
- `GET /api/estoque/rastreabilidade/lotes`
- `POST /api/estoque/rastreabilidade/verificar`
- `PUT /api/estoque/rastreabilidade/vinculos/<vinculo_id>`
- `GET /api/estoque/rastreabilidade/lote`
- `PUT|DELETE /api/estoque/produtos/<produto_id>`
- `POST /api/estoque/produtos/<produto_id>/ajuste`
- `GET /api/estoque/conferencias/<conferencia_id>`
- `POST /api/estoque/conferencias/<conferencia_id>/confirmar`
- `POST /api/estoque/nfe/preview_fabrica`
- `POST /api/estoque/nfe/direcionar`
- `POST /api/estoque/nfe/direcionar/lote`

Esses endpoints cobrem ajustes auditados, posicao por produto, consulta de
lote, rastreabilidade, conferencia e direcionamento para estoque/manutencao.

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
