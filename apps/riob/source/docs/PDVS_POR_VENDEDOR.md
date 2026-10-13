# Totais de PDVs por vendedor

Dados > RioB > Totais de PDVs por vendedor abre `#vendas:pdvs_totais`.
Nos perfis com menu por modulo, fica em Import/Export > RioB.
Importar o PDF **COBERTURA VENDEDOR/SUPERV.**, conferir vendedor, total anterior
e novo total, e confirmar. A atualizacao substitui somente os vendedores
confirmados; os outros permanecem. Zero e permitido, mas nao produz percentual.

O leitor usa **Total Clientes** da linha de cada vendedor, identificado pelo
codigo da base de vendas. Ignora linhas de cidades e o total geral. Clientes
C/Compra do PDF aparecem somente para conferencia: os PDVs com venda do resumo
continuam vindo do SELLOUT e dos filtros de periodo/grupos. Verifica que Total
Clientes corresponde a C/Compra + Negativos. Codigos desconhecidos nao sao
associados por similaridade de nome; o texto do PDF fica visivel para conferencia
e e possivel selecionar/adicionar um vendedor conhecido e corrigir seu total.
PDFs precisam conter texto selecionavel, ate 10 MB/100 paginas, sem senha.

Exemplo validado: SETEMBRO.pdf, setembro de 2026, 10 vendedores e 4.297 PDVs.
Vinicius: 408; Dirceu: 455; Sandro: 462; Amarildo: 448; Marcos Leandro: 499;
Valdecir: 237; Gerson: 448; Antonio Carlos: 448; Alex Sander: 458; Ricardo (22): 434.
Codigo 11 (outro Ricardo) nao recebe o total do codigo 22. Grafias do mesmo
codigo, como ALEX SANDER/ALEXSANDER, compartilham carteira.

## Calculo

Em Relatorios > RioB > Vendas > Grupos Embalagem:

- `PDVs com venda`: quantidade distinta de PDVs nos filtros atuais.
- `Total de PDVs da carteira`: total atual importado do vendedor; independente
  das datas, grupos e PDV escolhido. 8 PDVs na faixa 6 / carteira 400 = **2%**.
- Sem vendedor, soma as carteiras por codigo, incluindo carteiras sem vendas
  no periodo. Se algum vendedor presente no periodo nao tem total, percentual
  fica pendente e informa os cadastros faltantes. O PDF agregado nao permite
  deduplicar clientes compartilhados entre carteiras: o denominador geral e
  soma de carteiras, nao numero de clientes unicos da empresa.
- Sem carteira ou com total zero: percentual pendente, nunca substituido pelos
  PDVs que compraram. Se vendas superam a carteira, mostra aviso sem truncar.
- A ultima carteira confirmada vale tambem para periodos anteriores. A data do
  PDF nao cria vigencia historica. A media de grupos continua sobre PDVs com venda.
- Revisao persistida integra chaves dos caches do mix e dashboards em todos os
  processos. Ao atualizar, a proxima consulta utiliza a nova carteira.

## Persistencia e APIs

Schema idempotente no startup: `vendas_pdvs_totais` (uma carteira por codigo) e
`vendas_pdvs_importacoes` (PDF original, nome, usuario, data e totais antes/depois).
Gravacao transacional, sem apagar carteira ausente. Revisao da conferencia
bloqueia sobrescrita concorrente com 409; falhas fazem rollback.

`GET /api/vendas/pdvs-totais` lista carteira e vendedores conhecidos.
`POST /api/vendas/pdvs-totais/conferir` recebe multipart `arquivo`, devolve
candidatos, texto e revisoes atuais; nao grava dados.
`POST /api/vendas/pdvs-totais` recebe `arquivo`, `itens` JSON e `anteriores`
JSON, revalida PDF/vendedores/inteiros/duplicatas e confirma atualizacao.

Recurso proprio `riob:vendas_pdvs` em Config > Usuarios e acessos. Consulta,
conferencia e escrita exigem sessao do portal e esse recurso; proxy valida
contrato e bloqueio individual do menu, blueprint valida cabecalhos da sessao.
Sem concessao automatica. Ler percentuais permanece em `riob:vendas`.
Render segue somente leitura e sem proxy para o RioB local.

Testes: `test_vendas_pdvs.py`, `test_vendas_mix_grupos.py`,
`tests/test_vendas_reports_access.py`, `tests/check_vendas_pdvs.py`.

## Total importado visivel com carteira parcial (05/10/2026)

`resumo_geral.total_carteira_importada` informa a soma cadastrada no escopo,
mesmo quando ha vendedores sem carteira. `total_carteira` continua sendo o
 denominador completo, nulo quando faltam cadastros. O card mostra **PDVs
importados (parcial)** e o aviso lista os vendedores faltantes; nao divide as
vendas de todos por uma base parcial. Com vendedor cadastrado, o percentual e
calculado normalmente. Zero cadastrado aparece como zero; ausencia e pendente.

Diagnostico real: importacao 1 contem 4.297 PDVs; em setembro de 2026 o geral
inclui vendas dos autonomos 012, 014 e 033, ausentes do PDF. Isso nao indica
falha na importacao. Vinicius tem carteira 408, com 8 PDVs na faixa 6 (1,96%).
Nao e necessario reimportar o arquivo. O prompt enviado ao Ollama local esta
em `docs/PROMPT_OLLAMA_PDVS_PENDENTE.md` na raiz; o executor revisa a resposta,
integra a alteracao e verifica testes antes do deploy. Nenhum total e inventado.

Correcao de 10/10/2026: o calculo central `resumo_carteira` permanece no modulo
`vendas_pdvs`, separando a soma importada do denominador completo. O relatorio
de grupos de embalagem usa essa funcao e nao deve falhar quando a carteira for
parcial ou estiver vazia.
