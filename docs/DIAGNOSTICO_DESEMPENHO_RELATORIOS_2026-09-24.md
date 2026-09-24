# Diagnostico de desempenho dos relatorios

Consulta solicitada em 24/09/2026, com foco em vendas no Rio Branco.
Esta primeira parte registra o diagnostico anterior a autorizacao de implementar;
a implementacao e a validacao posterior estao no final.
Foram inspecionados o codigo e o ambiente local em execucao, usando consultas
SQL somente leitura, EXPLAIN e GETs dos relatorios. Nenhum dado, indice,
parametro global do banco ou servico foi alterado. Nao houve deploy.

## Medicoes

O `server.py` do container `riobranco-app` tem o mesmo SHA-256 do checkout
na revisao `b1f8ab8`. As alteracoes preexistentes de outros trabalhos foram
preservadas.

| Operacao | Tempo observado |
| --- | ---: |
| Abrir conexao com o MariaDB e iniciar transacao de leitura | 7,83 ms |
| SELECT 1 na conexao aberta | 0,49 ms |
| GET /api/vendas/meses, primeira medicao | 1,055 s |
| Relatorio mensal de bonificacoes, setembro/2026, primeira medicao | 2,985 s |
| Mesmo relatorio mensal, repeticao imediata | 0,048 s |
| GET /api/vendas/meses, repeticao | 0,021 s |
| Relatorio percentual de vendas anual, primeira medicao | 39,476 s |
| Mesmo relatorio anual, repeticao imediata | 0,021 s |

As chamadas HTTP usaram o proxy HTTPS em loopback, com resposta 200, sem passar
pelo shell/autorizacao do portal nem medir a renderizacao no navegador. Sao
amostras pontuais com o sistema em uso, nao percentis nem teste de carga. Nao
foi limpo o cache da aplicacao ou do banco; "primeira medicao" nao significa
cache de disco frio. A diferenca entre chamadas e consistente com o cache de
respostas existente no codigo.

Base ativa: `sellout-mensal-continuo`, com 426.593 itens distribuidos em 16
meses; setembro/2026 tem 16.076 itens. O mensal respondeu aproximadamente
343 KiB, incluindo 3.056 opcoes de clientes; o anual respondeu 4,2 KiB.

## Causas e oportunidades identificadas

### 1. O anual carrega e ordena o historico inteiro

Em `apps/riob/source/server.py`, `_vendas_relatorio_base_rows` busca 19 campos
de cada item, ordena por vendedor/cliente/cidade/produto/nota e usa `fetchall()`.
`_coletar_relatorio_vendas_percentual_vendas_anual` monta opcoes e filtra
vendedor/cliente em Python antes de calcular os totais mensais.

O EXPLAIN de uma projecao representativa dessa consulta, com os mesmos filtros
e ordenacao, mostrou `type=ALL`, sem indice escolhido, estimativa de 404.000
linhas e `Using where; Using filesort`. A estimativa difere da contagem real.
`filesort` comprova ordenacao adicional; sozinho nao comprova uso de disco.

Melhoria prioritária: calcular os totais mensais no SQL, aplicar filtros de
vendedor/cliente antes da leitura e consultar opcoes separadamente. Limitar
o periodo aos anos relevantes depois de determinar a referencia da base.
A ordenacao por produto/nota nao e necessaria para somar meses.

Um prototipo somente leitura com SUM(litros) por mes retornou 16 linhas em
11,228 s. Ele demonstra reducao de transferencia, mas NAO e uma implementacao
equivalente nem um tempo previsto para a tela: faltam opcoes, regras completas
de bonificacao, periodo comparavel e arredondamento por item. A consulta ainda
e lenta neste ambiente, reforcando a necessidade de investigar o banco tambem.

### 2. Cache de paginas do banco pequeno para a base

MariaDB 10.11.16, `innodb_buffer_pool_size=134217728` (128 MiB).
Somente `vendas_relatorio_itens` ocupa aproximadamente 288,4 MiB de dados e
517,8 MiB de indices. As bases de negocio somam aproximadamente 1.607,5 MiB.
O host tem 32.091 MiB de RAM e cerca de 25.176 MiB disponiveis na amostra,
sem uso de swap.

Os contadores acumulados desde o startup mostraram 390.428.959 pedidos de
leitura de paginas e 325.320.027 leituras pelo InnoDB. Esse historico inclui
importacoes e outras cargas: nao deve ser interpretado como taxa exclusiva
dos relatorios nem como medicao de latencia do disco fisico.

Proposta para teste controlado neste host: buffer pool de 2 GiB, medindo os
deltas desses contadores, memoria e tempos antes/depois sob a mesma consulta.
Dimensionar novamente se a carga crescer; nao aplicar o mesmo valor a todos
os clientes. O tamanho e uma proposta baseada neste ambiente, ainda nao
validada. Preservar configuracao por deploy e persistencia no container.

O buffer pool conserva paginas de dados e indices em memoria; seu
dimensionamento deve considerar outras cargas do servidor. Referencia:
[documentacao oficial do MariaDB](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-buffer-pool).

### 3. Cache de respostas perde validade a cada cinco minutos

`_VENDAS_RELATORIO_CACHE_TTL=300` e `_VENDAS_RELATORIO_CACHE_MAX=24`.
Filtros distintos concorrem pelos mesmos 24 espacos, incluindo bases de linhas
e respostas prontas. O anual volta a pagar o custo da leitura apos expiracao,
eviccao ou reinicio. Nao existe coordenacao para que duas requisicoes iguais
aguardem o mesmo calculo em andamento.

A base mensal continua ja inclui assinatura, quantidade e `updated_at` na
chave do cache. E possivel aproveitar essa revisao para manter resumos
compactos por mais tempo e invalidar quando a importacao mudar. Nao basta
aumentar o TTL de centenas de milhares de dicionarios em memoria; primeiro
reduzir o resultado armazenado e garantir limite de memoria.

### 4. O mensal faz trabalho repetido

Na base mensal continua, `_vendas_cache_bonificacoes_carregar` le todos os
itens do mes para `_vendas_bonificacoes_cache_processar` calcular grupos e
opcoes em Python. Depois, `_vendas_bonificacoes_payload` executa agregacoes
SQL de totais e vendedores. Com filtros, busca novamente detalhes e recalcula
em Python. Ha oportunidade de reutilizar agregacoes e obter apenas detalhes
necessarios, preservando contagens e calculos atuais.

O EXPLAIN representativo do mes usa o indice existente
`idx_vendas_relatorio_itens_data`, com leitura por intervalo. Nao ha evidencia
de que adicionar mais indices indiscriminadamente resolva o problema.

### 5. A tela espera uma consulta adicional em cada atualizacao

Em `apps/riob/source/script.js`, `carregarRelatorioVendas` sempre aguarda
`_vendasCarregarMeses` antes de pedir o relatorio. Reutilizar a lista de meses
durante a tela e deduplicar chamadas concorrentes elimina essa espera extra.
Garantir atualizacao apos troca/importacao da base e impedir que uma resposta
antiga substitua o filtro mais recente.

## Ordem sugerida e criterios de aceite

1. Medir e ajustar o buffer pool neste deploy; repetir a consulta com a mesma
   base e registrar memoria e contadores por intervalo.
2. Substituir a leitura integral do anual por agregacoes e filtros no SQL.
3. Otimizar o mensal e manter resumos compactos por revisao da importacao.
4. Eliminar requisicoes redundantes da tela e medir o caminho completo pelo
   portal e navegador, incluindo outros relatorios mais utilizados.

Antes de publicar codigo, comparar resultados antigos/novos para vendedor,
cliente, bonificacoes, devolucoes, meses sem vendas, arredondamento por item e
ano parcial. A lista de clientes do anual apresentou apenas uma opcao:
`_vendas_relatorio_base_rows` renomeia `cliente_norm` para `chave`, mas
`_vendas_publicar_opcoes_relatorio` procura `cliente_norm`. Incluir essa
inconsistencia na cobertura dos filtros durante a implementacao.

Preservar `riob:vendas`, os atalhos dos manifests e os bloqueios individuais
de Config > Usuarios e acessos. Mudancas de funcao precisam de documentacao,
revisao do catalogo e testes de usuario autorizado/nao autorizado. Nenhuma
otimizacao deve conceder acesso automaticamente.

O diagnostico concentra-se em vendas no ambiente local. Nao houve verificacao
de desempenho do Render, dos demais clientes ou de todos os relatorios. Nao
houve alteracao funcional nem promessa de ganho apos uma mudanca ainda nao
aplicada.

## Implementacao autorizada e validada

Apos o diagnostico, o usuario autorizou implementar e publicar no Git.

- Anual: agregacao de volumes iguais por mes no SQL, filtros aplicados antes
  da transferencia, referencia independente dos filtros e opcoes agrupadas.
  Os 426.593 itens deixam de ser materializados individualmente no Python.
  A lista anual agora expoe 5.894 clientes, preservando as chaves de filtro.
- Mensal: elimina agregacoes descartadas no caminho filtrado; reutiliza somas
  por vendedor no total, conservando contagens distintas; busca apenas campos
  usados no resumo e reutiliza a classificacao dos vendedores.
- Cache: resumos compactos da base continua duram ate uma hora com invalidacao
  por revisao; maximo de 24 entradas e descarte por uso menos recente.
- Tela: compartilha consulta de meses por 60 segundos, invalida apos atualizacao
  da configuracao/importacao e ignora respostas de filtros anteriores.
- Metadados: deixam de carregar JSONs inteiros dos relatorios sem necessidade.
- Acessos: manifest atualizado com a descricao de relatorios mensais/anuais no
  recurso existente `vendas`; servidor e bloqueios individuais preservados.

O buffer pool local foi efetivamente ajustado para 2.147.483.648 bytes (2 GiB).
A tentativa dinamica foi recusada com Warning 1292: o MariaDB 10.11.16 fixa
`innodb_buffer_pool_size_max` no startup. Foi necessaria uma reinicializacao
separada do banco apos configurar `/etc/mysql/conf.d/90-nanotech-memory.cnf`.
O mesmo container e volume `nanotechsoft_notechsoft_mysql` foram preservados,
sem migracao, restauracao ou sincronizacao. `NS_DB_BUFFER_POOL_SIZE=2G` fica
no arquivo local ignorado pelo Git; o Compose suporta o parametro para futuras
criacao/recriacao explicitas do banco, sem introduzir operacoes no update.
Referencia da limitacao:
[MariaDB, innodb_buffer_pool_size_max](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-system-variables#innodb_buffer_pool_size_max).

A versao foi construida por `up.sh` a partir de um worktree isolado, preservando
os binds e volumes originais. Alteracoes de outros trabalhos no checkout
principal nao foram incluidas nas imagens ou na publicacao.

Validacao realizada: comparativo anual, filtros combinados, arredondamento por
item (incluindo empates e negativos), ano parcial, expiracao/invalidation do
cache, LRU, testes SELLOUT, autorizacao e bloqueios individuais, scripts de
deploy e comportamento JavaScript de concorrencia/falha/ordem de respostas.
O SQL foi executado contra tabelas temporarias, e os resultados reais foram
comparados com a resposta anterior. Totais anuais, comparativos mensais,
resumos de bonificacoes, vendedores e detalhes filtrados foram preservados.

Na primeira validacao da versao em execucao, o anual respondeu em 14,858 s e
a repeticao em 0,107 s, contra os 39,476 s do diagnostico inicial. Sao amostras
com cargas concorrentes, nao garantia de latencia: a primeira abertura do anual
ainda pode demorar, principalmente com cache vazio. A leitura mensal filtrada
respondeu em 0,376 s. O Render nao executa RioB; sua revisao deve ser verificada
separadamente apos o push, sem acessar ou sincronizar bancos locais.

Depois do ultimo ajuste do mensal e de um novo deploy, o mensal sem filtro
respondeu em 5,155 s, o filtrado em 0,364 s e a repeticao em 0,213 s. A primeira
abertura mensal ainda varia com a carga: nao houve ganho comprovado contra
os 2,985 s da primeira amostra do diagnostico (outra amostra anterior a mudanca
levou 6,831 s). Todos os totais, vendedores, grupos e detalhes comparados
permaneceram identicos. O ganho medido mais claro foi no anual e na reutilizacao
dos resumos por mais tempo; o mensal frio ainda pode receber otimizacoes futuras.

O fluxo de publicacao tambem teve corrigida a lista de menus usada pelo
validador quando Flask nao esta instalado no host: `gestao`, `monitor` e `docs`
ja sao secoes do portal e nao devem bloquear o Git seguro. A validacao completa
de acessos foi executada no container com as dependencias instaladas.
