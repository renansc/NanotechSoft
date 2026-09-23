# Contagem, desperdicio e sobras

Em 11/09/2026 o usuario definiu que finalizar a contagem ajusta os saldos para as
quantidades fisicas, com historico. O fluxo esta em ESTOQUE > Contagem.

A lista e o popup de conferencia reutilizam a divisao do estoque por area e
grupo cadastrado: Producao / Produtos (Retornavel, PET, Agua etc.), Producao /
Materia-prima e Almoxarifado geral, incluindo grupos personalizados. A busca
mostra somente os grupos com produtos encontrados e preserva os valores
digitados; finalizar inclui todos os produtos contados, mesmo fora da busca.

1. Preencher pallets, caixas (CX) ou pacotes (PCT), e unidades soltas, no mesmo
   formato do Acerto. A embalagem de cada produto e sua capacidade aparecem
   junto ao campo. Saldo consultado e total contado usam a apresentacao do
   Acerto: pallets e caixas/pacotes na primeira linha, total exato em unidades
   abaixo. O popup usa essa apresentacao com os fatores conferidos no servidor.
   Campo vazio nao significa zero;
   produtos nao preenchidos ficam fora. Para zerar um saldo, informar zero.
2. Finalizar contagem consulta o saldo canonico atualizado no servidor, converte
   as embalagens pelas capacidades cadastradas e abre o popup de conferencia.
   O popup mostra somente produtos contados, saldo atual, total, diferenca e
   classificacao. E possivel voltar e corrigir; abrir o popup nao altera estoque.
3. Confirmar e ajustar estoque grava todos os ajustes e a finalizacao em uma
   unica transacao. Se o saldo ou as capacidades mudaram desde o popup, retorna
   409 e exige nova conferencia. Falha SQL reverte todos os ajustes.
4. Faltas (contado menor que saldo) sao registradas como desperdicio. Sobras
   (contado maior) sao marcadas como possivel erro de contagem. Nao compensar
   sobras e faltas entre produtos. Quantidades e contadores usam unidades.

O saldo e recalculado no servidor; nao sao aceitos saldo/diferenca enviados pelo
navegador. Cadastros que representam o mesmo produto canonico nao podem ser
contados duas vezes na mesma finalizacao. Rascunhos continuam na pagina e podem
ser exportados em CSV; somente contagens confirmadas alimentam os contadores.

## Persistencia e concorrencia

`estoque_contagens` guarda responsavel, observacao, criacao e finalizacao.
`estoque_contagem_resultados` guarda produto e codigos da epoca, saldo anterior,
quantidades digitadas, fatores de conversao, total contado, diferenca, desperdicio,
sobra e movimento gerado. Esses registros sao snapshots para auditoria.
As tabelas sao criadas idempotentemente pelo startup, sem restaurar dados.
Nao reutilizar `estoque_conferencias`, que pertence a conferencia de notas XML.

Movimentos usam `referencia_tipo=contagem_estoque` e o ID unico do item contado
como `referencia_id`, com entrada para sobras e saida para faltas. O ajuste
preserva o ultimo valor unitario conhecido. A linha da
contagem e bloqueada ate o commit; repetir a confirmacao retorna o resultado
existente, sem repetir ajuste ou contador. Durante a confirmacao, o livro de
movimentos e bloqueado em REPEATABLE READ, incluindo lacunas de insercao, para
serializar tambem os fluxos legados que nao possuem trava por produto. Produtos
sao relidos com bloqueio. A projecao canonica usa leitura separada somente apos
essa trava, pelo modo interno `somente_saldos` do resumo existente: reutiliza a
consolidacao de movimentos sem carregar indicadores ou importar fontes de vendas.
O bloqueio dura apenas a conferencia final e gravacao da transacao.
Depois do commit, a rotina existente de estoque minimo e reavaliada. Uma falha
nessa rotina nao desfaz a contagem ja salva; a resposta apresenta um aviso.

## Relatorio

RELATORIOS > Contagens, desperdicio e sobras possui filtros por datas inclusivas,
produto/codigo/responsavel e classificacao: todas, desperdicio, sobra ou sem
diferenca. Totais abrangem todos os registros filtrados; a lista pagina de 50
em 50. O PDF usa os mesmos filtros e inclui todas as paginas. Contagens apenas
conferidas/canceladas no popup nao entram. O relatorio preserva dados de produtos
que venham a ser renomeados ou removidos.

## APIs e permissoes

- POST `/api/estoque/contagens/conferir`: itens com produto_id, pallets, volumes,
  unidades e observacao geral opcional; retorna o ID da conferencia.
- POST `/api/estoque/contagens/<id>/finalizar`: confirma o snapshot desse ID.
  Somente responsavel ou administrador pode finalizar a conferencia.
- GET `/api/estoque/contagens/relatorio` e `/relatorio/pdf`: filtros inicio, fim,
  q e tipo; pagina vale somente para a lista JSON.

O manifest preserva `estoque_contagem` para leitura/CSV, exibido no catalogo
como Contagem por tipo (pallets, CX/PCT e unidades), sem alterar a chave
ou conceder acesso adicional. A concessao
`estoque_contagem_finalizar` permite conferir e ajustar, e e declarada em
`access_resources` para nao duplicar o menu. `estoque_contagem_relatorio` libera
a consulta e PDF. Para operadores, liberar Contagem e Finalizar contagem em
CONFIGURAR > Usuarios e acessos; nenhum acesso antigo e ampliado automaticamente.
Administradores e acesso integral ao RioB incluem as novas funcoes. Portal e
backend RioB verificam os recursos. Cabecalhos X-Usuario-* vem da sessao unica
via proxy; nao existe login local novo. Render continua bloqueando escritas.

Validacao: `tests/test_estoque_contagem.py` usa banco temporario isolado para
confirmacao, rollback, repeticao, zero, conversoes, filtros e permissoes.
`tests/test_menu_pdf.py` da raiz cobre o proxy e os recursos dos manifests.
`tests/check_estoque_contagem.py` valida o popup desktop/mobile, campos vazios,
conflito de saldo, confirmacao unica e navegacao do relatorio com APIs sinteticas.
