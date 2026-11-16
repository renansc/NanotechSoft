# SPED Fiscal

Aplicativo integrado ao portal para analisar arquivos EFD ICMS/IPI em TXT.
O TXT integral e os dados usados nos paineis permanecem no navegador. Durante
a importacao, o app envia ao RioB somente um resumo dos itens de entrada C170
necessario para consultar referencias de preco no Custo do produto.

Os codigos internos de unidade usados no C170 sao resolvidos pelo cadastro 0190
do proprio arquivo antes da sincronizacao (por exemplo, `31` pode ser enviado
como `KG`). O valor unitario exibido e sincronizado considera o desconto do item:
`(VL_ITEM - VL_DESC) / QTD`.

Na tela de importacao, o contador e os estados de leitura e analise permanecem
no conteudo integrado ao portal, permitindo acompanhar todo o processamento.

## Funcoes e acessos

As funcoes aparecem separadamente em **Config > Usuarios e acessos** e nao sao
concedidas automaticamente:

- `sped:dashboard`: painel multianual;
- `sped:importar`: importacao de TXT, remocao e backup JSON local;
- `sped:analise`: registros C100, C190, 0200, E110, H010, K230 e K235;
- `sped:comparativo`: comparacao entre exercicios;
- `sped:transacoes`: clientes, fornecedores e itens C170;
- `sped:tributos`: acompanhamento preliminar dos tributos escriturados;
- `sped:grupos`: agrupamentos manuais e relatorios por fornecedor;
- `sped:config`: regime tributario por exercicio.

Em **Relatorios > Clientes e transacoes SPED**, a consulta inicia com todas as
operacoes para que bases contendo somente itens de entrada C170 continuem
pesquisaveis. Produto, cliente/fornecedor e documento fiscal possuem seletores
independentes e combinaveis. A escolha do produto restringe os clientes e
documentos disponiveis; a escolha do cliente restringe os documentos. Cada
documento identifica numero, data, participante e final da chave quando houver.
O estado da consulta informa a quantidade encontrada e os filtros ativos;
**Limpar filtros** restaura a consulta completa.

O servidor exige a sessao unica e o contrato do deploy para servir qualquer
arquivo do app. Cada tarefa usa `?view=...`, permitindo que o servidor aplique o
mesmo catalogo individual usado no menu principal antes de entregar a pagina.

## Dados e limites

- O TXT e processado no navegador e nao e armazenado. A base analitica resultante
  e persistida em `sped_bases`, por empresa e periodo, e restaurada
  automaticamente ao abrir qualquer tela do app. O JSON continua disponivel
  como copia de seguranca manual.
- Para usuarios que tambem possuem `riob:custo_produto`, cada periodo importado
  substitui o resumo anterior da mesma empresa/periodo em
  `custo_produto_sped_itens`. Sao gravados apenas empresa, periodo, documento,
  fornecedor, produto, unidade, quantidade, valor, desconto e CFOP; o TXT nao e
  enviado nem armazenado. Sem essa permissao, a analise local continua e a tela
  informa que as referencias nao foram sincronizadas.
- Agrupamentos e regimes sao persistidos em `sped_configuracoes` e compartilhados
  entre usuarios autorizados. O `localStorage` e apenas uma copia de contingencia.
- Os codigos de unidade `0190` confirmados nos EFD da Rio Branco (`1` kg, `4`
  unidade, `22` saco e `28`/`68`/`429` milheiro) tambem sao reconhecidos nas referencias antigas.
  Assim, rotulos de 2 L, 600 ml e 200 ml escriturados em milheiros sao convertidos
  exatamente para unidades; as dimensoes `33,5`, `23` e `16,6` cm identificam a
  apresentacao, mas nao precisam ser usadas como estimativa de quantidade.
- O app nao inclui TXT, RAR, JSON de backup, XML, certificado A1 ou sugestoes
  derivadas de dados de clientes no repositorio.
- A visualizacao de nota reproduz a escrituracao importada e nao consulta a
  SEFAZ. Uma integracao futura com certificado exige armazenamento seguro,
  autorizacao propria no servidor e testes adicionais.
- Classificacoes de CFOP e totais tributarios sao auxiliares e exigem conferencia
  contabil/fiscal antes de qualquer decisao.

## Deploy

O codigo fica em `apps/sped/source` e e publicado pelos comandos canonicos da
raiz. O perfil `rio-branco` contrata o modulo; o perfil `nanotech`, por possuir
o catalogo global, tambem o disponibiliza. Atualizacao de codigo nunca apaga,
restaura ou sincroniza arquivos SPED.

Validacoes focadas: `tests/test_sped.py` cobre manifest, contrato, rotas e
autorizacao; `tests/check_sped.py` processa um TXT sintetico no navegador sem
usar dados fiscais reais. A sincronizacao e o uso no custo sao cobertos por
`apps/riob/source/tests/test_custo_produto.py`.
