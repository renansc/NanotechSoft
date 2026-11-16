# Financeiro

O Financeiro é servido pelo portal Flask em `/apps/financeiro`, usa a sessão
única do NanotechSoft e persiste o estado operacional nas tabelas
`financeiro_registros` e `financeiro_config` do banco do portal.

## Plano de contas e amarrações

A função **Config > Plano de contas e amarrações** (`?view=contabilidade`)
mantém o plano contábil central usado pelo Financeiro e pelo Estoque. O acesso
individual é o recurso `financeiro:contabilidade`; ocultar o menu não substitui
a validação das APIs.

O plano aceita código único, nome, classificação, natureza devedora/credora,
conta pai, descrição e os indicadores analítica/sintética e ativa/inativa.
Somente contas analíticas e ativas podem receber amarrações. Uma conta com
filhas ou vínculos não pode ser excluída; ela pode ser inativada para preservar
o histórico.

A central lê dinamicamente os seguintes cadastros:

- Financeiro: contas financeiras, categorias e favorecidos;
- Estoque: grupos e produtos ativos;
- Compras/entrada: fornecedores ativos do cadastro canônico do RioB.

Os vínculos ficam em `contabil_vinculos`, identificados por aplicação, tipo e
ID do cadastro. O plano fica em `contabil_plano_contas`. Dessa forma nenhum app
mantém cópia do plano e uma mudança de conta é auditável por usuário e data.
Cadastros sem amarração aparecem como **Pendentes** e ainda não estão prontos
para exportação/integração contábil. A tela permite vincular individualmente ou
em lote.

### APIs

- `GET /apps/financeiro/api/accounting`: plano, cadastros, vínculos e cobertura;
- `POST /apps/financeiro/api/accounting/accounts`: cria conta;
- `PUT|DELETE /apps/financeiro/api/accounting/accounts/<id>`: altera ou exclui;
- `PUT /apps/financeiro/api/accounting/bindings`: grava ou remove vínculos.

Todas exigem login, app Financeiro liberado e o recurso `contabilidade`. No
Render somente leitura, as mutações continuam bloqueadas pela proteção global.

## Validação

```bash
python3 -m unittest tests.test_financeiro_contabilidade
python3 -m unittest tests.test_financeiro_dashboard tests.test_financeiro_favorecidos
```

No navegador, abra a função pelo menu Config, cadastre pelo menos uma conta
analítica e confirme que um vínculo individual e um vínculo em lote atualizam
os indicadores de vinculados e pendentes.
