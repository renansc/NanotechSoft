# Aprovação de XML e PDF no estoque

## Objetivo

A tela `Estoque > Aprovar XML e PDF` concentra o aceite dos documentos que
podem alterar o saldo:

- XML de entrada cria movimentos de entrada somente após confirmação;
- XML de saída cria movimentos de saída somente após confirmação e conserva o
  vínculo obrigatório com o frete, salvo retirada pelo cliente;
- PDF de carga encontrado em `RB_VENDAS_DIARIO_PDF_DIR` é preparado para
  conferência, mas só cria saídas depois do aceite explícito; cargas antigas
  podem ser rejeitadas e retiradas da fila sem movimentar estoque.

O recurso individual do portal é `estoque_documentos_aprovar`, com destino
`/apps/riob#estoque:documentos`. A API também valida sessão, perfil e recurso;
nenhuma permissão é concedida automaticamente.

## Fluxo dos PDFs compartilhados

`Ler pasta compartilhada` procura arquivos `.pdf` no diretório configurado,
extrai mapas e itens e atualiza `cargas` e `cargas_estoque_itens`. Essa leitura
não movimenta saldo. O documento permanece com situação `pendente` até o
operador abrir `Revisar e aceitar`.

A revisão mostra, por item:

- código e produto resolvidos;
- quantidade de embalagens e unidades soltas;
- fator usado na conversão;
- quantidade total que será baixada em unidades canônicas;
- saldo atual e saldo projetado.

Ao aceitar, o servidor bloqueia a carga, grava uma saída em
`estoque_movimentos` por item com `referencia_tipo=carga_pdf_item` e
`referencia_id=cargas_estoque_itens.id`, preenche
`cargas_estoque_itens.estoque_movimento_id` e registra usuário/data em
`cargas.estoque_baixado_por` e `cargas.estoque_baixado_em`. Repetir a chamada é
idempotente e não cria uma segunda baixa. A referência por item é obrigatória:
o índice único `(referencia_tipo, referencia_id)` continua protegendo contra
duplicidade sem impedir que uma carga com vários produtos gere vários
movimentos na mesma transação.

O aceite carrega o resumo canônico de saldos uma única vez e reutiliza essa
fotografia para todos os itens, descontando no cálculo projetado as linhas já
processadas da mesma carga. Não recalcule o relatório completo a cada item: em
cargas maiores isso ultrapassa o tempo de espera do navegador, apesar de a
transação continuar e concluir no servidor. Se a conexão for encerrada durante
o aceite, a interface reconcilia o estado da carga antes de informar falha; se
o servidor já tiver marcado `estoque_baixado_em`, mostra a conclusão real e não
induz o operador a repetir a operação.

Para uma carga que não precisa mais ser contabilizada, `Rejeitar` exige motivo
e uma confirmação explícita. A rejeição é lógica: preserva o PDF, a carga, os
itens e eventuais dados operacionais, mas a remove da fila padrão e impede
qualquer aceite posterior. O servidor grava data, usuário e motivo em
`cargas.estoque_rejeitado_em`, `cargas.estoque_rejeitado_por` e
`cargas.estoque_rejeitado_motivo`. Uma nova leitura da pasta não reativa a
carga. O filtro `Rejeitados` mantém o histórico consultável.

Cargas já baixadas ou cobertas por XML não podem ser rejeitadas. A rejeição não
apaga arquivo, não exclui registros físicos e não cria movimentos de estoque.

## Prevenção de duplicidade XML x PDF

A NF-e de saída é a fonte definitiva. Quando
`estoque_xml_frete_vinculos.carga_id` aponta para a carga do PDF, o documento
fica como `coberto_xml`. A confirmação do PDF retorna conflito e não cria
movimentos, porque o PDF representa a carga completa e uma nova baixa poderia
duplicar produtos já contabilizados pelas NF-e.

Alterar o frete para `carregado`, `entregando`, `retornando` ou
`paradoCarregado` não baixa mais o PDF automaticamente. O retorno operacional
indica `aguardando_aprovacao_documento`; somente a tela de aceite pode efetivar
a saída.

## API

- `POST /api/estoque/aprovacoes-pdf/sincronizar`: lê a pasta compartilhada sem
  movimentar estoque;
- `GET /api/estoque/aprovacoes-pdf`: lista pendentes, cobertos por XML, já
  baixados e rejeitados;
- `GET /api/estoque/aprovacoes-pdf/<carga_id>`: retorna a prévia dos itens e dos
  saldos;
- `POST /api/estoque/aprovacoes-pdf/<carga_id>/confirmar`: efetiva a baixa em
  uma transação;
- `POST /api/estoque/aprovacoes-pdf/<carga_id>/rejeitar`: exige `motivo`,
  registra a rejeição auditável e não movimenta estoque;
- `/api/estoque/importacoes-xml*`: mantém a fila e confirmação já existentes e
  também é autorizada pelo destino `estoque:documentos`.

Pasta ausente retorna `503` na sincronização, sem apagar a fila persistida. Um
PDF inválido aparece no resumo de erros e os demais arquivos continuam sendo
processados.

## Verificação

- `tests/test_estoque_documentos_access.py`: catálogo, recurso individual,
  proxy e presença da interface;
- `apps/riob/source/tests/test_estoque_aprovacao_documentos.py`: ausência de
  baixa automática, carga com múltiplos itens, bloqueios XML/PDF/rejeição,
  auditoria e estados públicos;
- testes existentes de importação XML e parsing de PDF permanecem obrigatórios.
