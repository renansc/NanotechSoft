# SELLOUT mensal automatico

O RioB consulta `smb://192.168.200.121/d/INDB/AnalyticsCTA/Dados/SELLOUT_M.CSV`
pelo compartilhamento CIFS ja montado no host em `/media/serverwin`.
O Compose expoe somente a pasta Dados em `/imports/sellout`, somente leitura.
Credenciais SMB permanecem na montagem do host, fora do codigo.

O arquivo verificado em setembro de 2026 possui 7.735 linhas, `Mes&Ano=09/2026`
e campos Data, Data Pedido, Data NFe e Numero nf vazios. Trata-se de consolidado
mensal, nao de lancamentos individuais. A rotina valida Mes&Ano de todas as
linhas antes de escrever. O primeiro dia do mes em `data_ref` representa somente
a competencia; `data_texto` registra `MM/AAAA (mensal)`. Essa fonte nao confirma
cards diarios nem permite relatorios de volume por dia.

## Operacao

- `RB_SELLOUT_M_AUTO=1` habilita a rotina no Compose local do RioB.
- `RB_SELLOUT_M_HOST_DIR` define a pasta montada no host.
- A leitura automatica acontece uma vez por dia, as 08:00 no fuso
  `America/Sao_Paulo`. `RB_SELLOUT_M_INTERVALO_MINUTOS` deixou de ser utilizado.
- Fora do Compose, definir tambem `RB_SELLOUT_M_ARQUIVO` com o caminho local.
- O startup apenas agenda a proxima ocorrencia das 08:00; nao importa o
  arquivo ao subir o app. Se o app iniciar depois desse horario, aguarda o dia
  seguinte. A rotina independe de navegador aberto e nao inicia no Render.
- O botao **Ler pastas automaticamente** le TXT, PDF e tambem o SELLOUT mensal
  imediatamente, em qualquer horario. Essa leitura nao muda o agendamento das
  08:00. Falhas de SELLOUT nao impedem a leitura dos TXT/PDF, e a resposta mostra
  atualizado, sem alteracoes, desabilitado, em processamento ou erro.
- A varredura periodica existente de TXT/PDF continua sem ler o SELLOUT mensal.
  O botao nao depende de `RB_SELLOUT_M_AUTO`, que controla somente o agendador;
  a habilitacao de Vendas e as permissoes do usuario continuam obrigatorias.
- Em caso de falha as 08:00, a proxima tentativa automatica ocorre no dia seguinte;
  o operador pode tentar antes pelo botao. O arquivo continua exigindo 60 segundos
  de estabilidade, inclusive na leitura manual.
- O arquivo precisa estar sem modificacao ha pelo menos 60 segundos; tamanho
  e mtime sao conferidos novamente depois da copia temporaria. O temporario
  e removido ao terminar, inclusive em caso de falha.

Os dados usam as tabelas existentes `vendas_relatorios_importados` e
`vendas_relatorio_itens`, com um unico identificador `sellout-mensal-continuo`.
SHA-256 do conteudo e assinatura das regras evitam reimportar um arquivo igual,
mesmo quando sua data de modificacao muda. Um lock MySQL impede duas gravacoes
simultaneas por processos diferentes.

Quando o arquivo muda, os meses presentes sao substituidos integralmente em
uma transacao junto com seus metadados. Isso atualiza valores consolidados,
novos clientes/produtos e correcoes sem somar duas vezes o acumulado mensal.
Meses ausentes sao preservados. Falha de leitura, competencia invalida, arquivo
vazio ou falha SQL mantem a base anterior, geram log e permitem nova tentativa manual ou no proximo dia.
Pressuposto: cada mes presente no arquivo e um consolidado completo daquele mes.
O produtor deve preferir publicar o CSV por troca atomica, pois nenhuma checagem
de mtime pode provar a completude de um exportador pausado por longo periodo.

Depois do commit, a base continua e selecionada automaticamente para os
relatorios. Projecoes de vendas dessa base consultam o banco sem exigir
"Processar relatorios" e sem acumular novos arquivos JSON. Projecoes em memoria
reutilizam o cache curto existente, identificado pela assinatura transacional
do conteudo para invalidacao entre processos. O historico de
estoque possui TTL preexistente de ate cinco minutos.

## Carga inicial do historico

A carga inicial e uma operacao explicita de dados em
`POST /api/vendas/sellout/historico`, independente do startup, agendador e deploy.
Aceita exatamente uma origem por requisicao:

- `{"arquivo": "VENDAS/2SELLOUT_D.CSV"}`: CSV relativo a pasta Relatorios.
- `{"import_id": "ID_DA_IMPORTACAO_ANTIGA"}`: arquivo original de uma importacao
  registrada anteriormente. Os registros antigos permanecem intactos.

A base continua deve existir antes dessa carga. O arquivo completo e validado
antes das gravacoes e separado em arquivos temporarios por competencia para
limitar memoria. Cada mes ausente e inserido em uma transacao, mantendo os
meses existentes (inclusive o mes corrente), mesmo se o historico se sobrepoe.
Repetir uma carga nao soma nem sobrescreve meses ja presentes. Se houver uma
falha entre meses, a resposta lista os concluidos e a repeticao retoma somente
os faltantes. Cada mes incluido registra origem, assinatura e quantidade em
`vendas_sellout_historico`, na mesma transacao dos itens.

Datas reais do campo Data sao mantidas quando pertencem a Mes&Ano. Linhas sem
data continuam marcadas como mensais. A assinatura do arquivo monitorado fica
intacta: acrescentar historico nao exige reimportar o mes corrente. As projecoes
consideram tambem quantidade acumulada e updated_at para invalidar os resultados
anteriores a carga inicial. Os arquivos temporarios sao removidos ao terminar.

O arquivo historico local `VENDAS/2SELLOUT_D.CSV` cobre junho a dezembro de 2025
e janeiro a marco de 2026. O upload `20260903_154559_SELLOUT_M.CSV` cobre agosto
2026. Janeiro a maio de 2025 e abril a julho de 2026 nao constam nessas fontes;
nao preencher esses periodos com zeros nem inferir seus valores.

Depois da carga inicial, a rotina diaria das 08:00 segue substituindo apenas as
competencias presentes no SELLOUT_M, preservando os demais meses do historico.

## Verificacao

`PYTHONPATH=apps/riob/source python3 -m unittest discover -s apps/riob/source/tests -p test_sellout_auto.py -v`

Na aplicacao, `Config > Vendas` lista a base continua, quantidade acumulada e
ultima atualizacao. Os logs de `riob-app` registram falhas de leitura/importacao. Subir o
codigo usa exclusivamente `./up.sh`; publicar codigo usa os comandos da raiz.

## Consulta e interface

Com a base continua ativa, Config > Vendas apresenta somente essa base. As
importacoes anteriores permanecem no banco para auditoria e carga historica,
sem opcoes de alternancia, exclusao ou processamento de caches no fluxo
automatico. `GET /api/vendas/meses` lista as competencias diretamente do indice
do banco antes de carregar indicadores. Relatorio e dashboard possuem seletor
de mes. O resumo de bonificacoes le somente o mes escolhido, evitando
materializar todo o historico para abrir uma tela mensal.

## Acessos da leitura manual

`POST /api/vendas/diario/importar` sem arquivo multipart aciona a leitura conjunta
com `incluir_sellout=True`. O envio de TXT individual continua importando somente
esse TXT. O recurso existente `riob:vendas` e mantido nos manifests e no servidor;
o catalogo em Configurar > Usuarios e acessos o identifica como
`Vendas e importacoes (TXT, PDF e SELLOUT)`. Nenhuma permissao e concedida
automaticamente. O proxy valida a sessao e o recurso; Render bloqueia escritas.
A leitura mensal continua atualizando consolidacoes mensais, sem confirmar cards
diarios ou importar o historico por efeito colateral.
