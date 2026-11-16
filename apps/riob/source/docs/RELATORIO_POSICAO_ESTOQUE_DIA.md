# Posicao de estoque do dia por grupo

Em 22/10/2026 foi adicionada a consulta em `Relatorios > Posicao de estoque do
dia`. Ela reconstrói a fotografia do livro de movimentos no fim de qualquer dia
e organiza os produtos pelo grupo cadastrado.

Para cada produto e grupo, o relatório apresenta saldo inicial, entradas do
dia, saídas do dia e saldo final. Produtos com fator de embalagem mostram
pacotes/caixas inteiros, as unidades soltas restantes e o total em
unidades-base. Assim, 665 unidades de um produto com 12 unidades por pacote são
exibidas como `55 pacotes + 5 unidades soltas`, e não como pacote fracionado.
Totais de grupos permanecem
em unidades-base, pois reúnem produtos com embalagens diferentes. O saldo inicial considera movimentos
anteriores à data; o saldo final considera todos os movimentos até 23:59:59 do
dia selecionado. As quantidades permanecem em unidades-base do estoque e grupos
sem saldo ou movimento não são exibidos.

O agrupamento usa primeiro o `produto_id` resolvido pelo código canônico. Nomes
parecidos de produtos pertencentes a cadastros ou grupos diferentes não podem
ser somados na mesma linha. Isso evita, por exemplo, misturar bebida, rótulo e
insumo apenas porque suas descrições contêm o mesmo sabor e volume. A mesma
proteção é aplicada à posição atual; somente famílias vendidas de PET, água e
retornáveis podem consolidar IDs diferentes quando grupo e chave canônica são
iguais.

APIs:

- `GET /api/estoque/relatorio-posicao-dia?data=AAAA-MM-DD&grupo_estoque=CODIGO`
- `GET /api/estoque/relatorio-posicao-dia/pdf` com os mesmos filtros

A consulta usa `estoque_movimentos` como livro canônico e resolve os códigos
históricos pelos cadastros/aliases atuais de `estoque_produtos`. Alterações no
cadastro não reescrevem os movimentos. O PDF repete os totais de cada grupo e o
detalhamento dos produtos.

O item de menu usa o recurso existente `estoque`, mas possui destino individual
`relatorios:estoque_posicao_dia` no catálogo de Config > Usuários e acessos. O
proxy associa exclusivamente as duas APIs a esse destino, respeitando bloqueio
individual. Nenhuma permissão é concedida automaticamente e não existe login
local.
