# Baixas por perda

ESTOQUE > Baixas por perda (`#estoque:perdas`) registra desperdicio, avaria,
quebra, vencimento, extravio e outros motivos. Usa produtos ativos e o mesmo
saldo canonico da contagem, consolidando cadastros equivalentes.

Nova baixa abre o formulario com produto, data da ocorrencia, motivo e
justificativa obrigatoria. A quantidade pode ser informada em pallets,
caixas/pacotes e unidades de estoque, conforme capacidades cadastradas. Materia
prima preserva a unidade cadastrada; bebidas usam unidades individuais. Saldo
anterior, conversoes e saldo posterior sao calculados no servidor.

Conferir baixa prepara um snapshot, sem movimentar estoque. Confirmar baixa no
estoque grava uma saida e o historico em uma unica transacao. Quantidade deve
ser positiva, com ate tres casas decimais, e nao pode superar o saldo.
Pallets e caixas/pacotes sao inteiros. Data nao pode ser futura.

`estoque_perdas` preserva produto/codigos/unidade/grupo da epoca, quantidades,
fatores de conversao, motivo, justificativa, responsavel da sessao e datas.
Data de ocorrencia e separada da data efetiva de confirmacao: informar uma data
passada nao reescreve o saldo historico. A saida usa
`referencia_tipo=perda_estoque`, `referencia_id` da baixa e nota `PERDA-<id>`.
Preserva o ultimo valor unitario conhecido do estoque. Movimentos vinculados
nao podem ser alterados/excluidos pelo historico generico existente.

A confirmacao bloqueia a baixa e o livro de movimentos em REPEATABLE READ,
como a contagem existente. Mudanca de saldo, identidade canonica ou embalagem
retorna 409 e exige nova conferencia. Repetir a confirmacao do mesmo ID retorna
o registro existente, sem duplicar a saida. Falha SQL reverte toda a operacao.
Somente responsavel ou administrador confirma. Apos commit, reavalia o estoque
minimo pelas regras existentes; uma falha nessa verificacao retorna aviso,
sem desfazer a baixa salva.

A proxima contagem usa o saldo ja reduzido; o mesmo desperdicio nao e contado
novamente. Uma contagem conferida antes da perda deve ser reconferida antes de
finalizar. Se a perda ja foi descontada por uma contagem finalizada, nao deve
ser lancada novamente aqui. Esta tela registra novas baixas, nao altera as
justificativas de contagens antigas. Custo diario continua com sua fonte
existente de contagens; esta funcao contabiliza quantidades no estoque.

O historico mostra somente baixas confirmadas, com periodo inclusivo por data
de ocorrencia, motivo, busca por produto/codigo/justificativa/responsavel e
paginacao de 50 registros. Totais sao separados por unidade, sem somar KG a UN.

## API e acessos

- GET `/api/estoque/perdas/produtos`: produtos, saldos, capacidades e motivos.
- POST `/api/estoque/perdas/conferir`: produto_id, data_ocorrencia, motivo,
  justificativa, pallets, volumes e unidades; retorna conferencia.
- POST `/api/estoque/perdas/<id>/finalizar`: confirma a baixa conferida.
- GET `/api/estoque/perdas`: inicio, fim, motivo, q e pagina.

Recurso proprio `estoque_perdas` em Config > Usuarios e acessos, declarado nos
manifests base e Rio Branco. Acesso a estoque ou contagem nao libera baixas por
perda automaticamente. Administradores e acesso integral ao RioB incluem a
funcao. Proxy e blueprint verificam autorizacao; bloqueio individual do menu
prevalece sobre acesso integral para usuarios comuns. Sessao continua unica;
Render permanece bloqueado para escrita. Schema criado idempotentemente pelo
startup; sem importacao, restauracao ou copia de bancos.

Validacao: `tests/test_estoque_perdas.py` no RioB cobre conversoes, saldo,
idempotencia, rollback, filtros, permissoes e integracao com contagem. A opcao
`RB_PERDAS_TEST_MYSQL=1` usa exclusivamente banco descartavel de testes, via
DB_HOST/DB_USER/DB_PASSWORD/DB_NAME. `tests/test_estoque_perdas_access.py` na
raiz cobre menu, recurso, liberacao isolada e bloqueios do proxy.
`tests/check_estoque_perdas.py` verifica formulario real, conversao, conflito,
confirmacao, historico/filtros e celular com APIs sinteticas, sem baixas reais.

## Validacao e aplicacao local — 01/10/2026

Aplicado com `./up.sh`, sem restaurar ou sincronizar bancos. Os 34 testes de
baixas, contagem, menu e autorizacao passaram; oito casos tambem passaram em
MariaDB descartavel (a injecao de rollback foi validada no adaptador isolado).
Formulario validado em desktop e celular, com conflito, confirmacao e escape
de justificativas. No portal HTTPS real foram conferidos submenu, produtos,
saldos, formulario e historico, somente por leitura e sem registrar perdas
operacionais. Codigo em execucao corresponde ao workspace. Aplicacao local;
nenhum commit/push foi feito nesta tarefa.
