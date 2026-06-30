# Documentacao do Projeto RioBranco

Este diretorio concentra a documentacao tecnica principal do sistema.

## Arquivos

- `ARQUITETURA_SISTEMA.md`
  - visao geral da arquitetura, modulos, integracoes, kanban operacional e papel do `dashboards.html`

- `DIAGRAMAS_E_PROCESSOS.md`
  - fluxogramas e diagramas Mermaid dos processos operacionais e tecnicos principais

- `OPERACAO_E_DEPLOY.md`
  - runbook de deploy, atualizacao, backup, restore, certificados, SIP, uso do kanban e operacao do modo TV

- `NFE_RECEITA_E_INTEGRACAO.md`
  - passo a passo operacional da NF-e, configuracao do DF-e, uso do portal oficial, XML manual, sincronizacao por NSU e testes de integracao

- `API_E_DADOS.md`
  - referencia de API, dominios funcionais, principais payloads, entidades e modelo de dados

## Ordem sugerida de leitura

1. `ARQUITETURA_SISTEMA.md`
2. `DIAGRAMAS_E_PROCESSOS.md`
3. `OPERACAO_E_DEPLOY.md`
4. `NFE_RECEITA_E_INTEGRACAO.md`
5. `API_E_DADOS.md`

## Objetivo

O objetivo deste conjunto de documentos e permitir que outra pessoa consiga:

- entender a arquitetura real do sistema
- operar deploy e manutencao sem depender de conhecimento tacito
- diagnosticar os problemas mais comuns
- consultar a API e o banco com contexto funcional

## Cobertura funcional explicita

Os documentos tambem passam a explicar de forma direta:

- como o kanban operacional de fretes funciona no dashboard, para que serve e como mover fretes entre colunas
- quais status do banco aparecem em cada coluna do kanban
- o que e o arquivo `dashboards.html`, para que serve e quando usar em TV, monitor ou tela dedicada
- que a operacao continua sendo feita em `RioBranco.html`, enquanto `dashboards.html` e uma tela de exibicao automatica

## Atualizacoes recentes cobertas nesta revisao

Esta revisao da documentacao passa a registrar explicitamente:

- o modulo de estoque com dashboard proprio, movimentos, saldo, conferencia de almoxarifado e importacao de NF-e priorizando a chave bipada via DF-e, com XML/PDF como contingencia
- a leitura assistida de DANFE por foto no estoque e no abastecimento, incluindo OCR focado na grade de itens para extrair codigo, descricao, quantidade e valor sem substituir a consulta oficial da NF-e via DF-e
- o modo de foto manual dos itens no estoque, que abre a imagem como referencia visual ao lado da grade de digitacao para preservar desempenho mesmo em celulares e containers sem aceleracao
- o app Android complementar em `mobile-companion-android/`, que usa OCR local no proprio aparelho e envia os itens para a API de importacao do estoque
- a configuracao NF-e em `Config -> NF-e`, incluindo portal assistido, DF-e, ambiente SEFAZ, UF autora, certificado, senha e ultimo NSU
- o modulo `Vendas -> Relatorio`, com leitura do CSV externo, importacao persistida no banco e configuracao em `Config -> Vendas`, incluindo importacao manual do CSV, lista de relatorios importados, selecao do relatorio ativo e agrupadores por vendedor, cidade e produto
- os alertas sonoros do chat interno para novas mensagens e eventos de chamada SIP
- o passo a passo dedicado de operacao com NF-e / Receita, deixando explicito o que hoje e automatico no DF-e e o que ainda depende de XML/manual
- o fluxo portal assistido da Receita com abertura da consulta publica ja preparada com a chave bipada, para reduzir a operacao manual ao reCAPTCHA e ao uso do bookmarklet
- o uso de `codbar_modo` por usuario para definir se o fluxo principal de leitura e por bip/leitor ou camera/webcam
- anexos no chat interno, com download controlado por participante da conversa
- importacao de XML da NF-e direto em abastecimentos, com preenchimento automatico de nota, emitente, litros e valor
- o monitor de cameras com grid lateral de ate 16 cameras, player ampliado no desktop e cadastro de novas cameras centralizado em `Config -> Cameras`
- o cadastro e os relatorios de lavagens, alem do PDF consolidado de frota por tipo de relatorio
- o portal `/docs/index.html`, com redirecionamento preservando host e porta customizada no Nginx
- o script `deploy/sync-production-to-homolog.sh`, seus cuidados operacionais e os artefatos gerados em `sync-backups/`
- os snapshots operacionais versionados em `sync-import/`, usados como referencia/importacao manual e nao como volume automatico do deploy
