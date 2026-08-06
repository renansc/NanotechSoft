# NanoStore

Sistema de gestao adaptavel a diferentes operacoes comerciais, separado do
`zap`, usando-o apenas como referencia arquitetural.

## O que esta pronto

- cadastro de categorias, fornecedores e produtos
- controle por lote, validade e localizacao
- vendas por balcao, WhatsApp, WooCommerce, WordPress, Mercado Livre e delivery
- faturamento individual e em massa com XML de simulacao assinado
- pagamentos com base para Pix e maquina de cartao
- configuracao de provedores e canais
- dashboard web inicial
- modos de apresentacao para farmacia, loja, distribuidora, comercio, alimentos
  e prestador de servicos

## Modos de operacao

O seletor no menu lateral grava `STORE_MODE` nas configuracoes do NanoStore.
Cada perfil altera a hierarquia de navegacao, a terminologia, os indicadores,
as acoes rapidas e a identidade visual sem duplicar os dados da empresa.

O modo `pharmacy` permanece como padrao. No modo `services`, itens podem ser
marcados sem controle de estoque e vendidos sem lote; materiais usados pelo
prestador continuam podendo controlar estoque normalmente. O faturamento de
mercadorias (NF-e/NFC-e) fica oculto nesse perfil porque servicos exigem um
fluxo proprio de NFS-e.

No modo `distributor`, a navegacao operacional e reduzida a Caixa, Pedidos e
Cadastros. O Caixa registra recebimentos, entradas, saidas e retiradas e oferece
emissao fiscal dos pedidos. Pedidos usam uma fila de separacao e entrega; o
destino deve ser uma mesa identificada ou uma entrega vinculada a cliente
cadastrado com telefone e endereco.

A interface da distribuidora possui identidade propria em dourado, preto e
branco: navegacao preta, selecao e acoes prioritarias douradas e paineis brancos
para manter leitura rapida no uso diario.

A navegacao segue um padrao de tres niveis: menu lateral para a area, submenu
horizontal para o modulo e um submenu de funcoes quando a tela possui operacoes
diferentes. Somente a funcao ativa permanece visivel, e o navegador guarda a
ultima escolha de cada area. Em telas estreitas, os submenus usam rolagem
horizontal; atalhos como `Novo produto` abrem diretamente o formulario correto.

Em `Configuracao > Logomarca`, a empresa pode enviar ou remover sua identidade
visual. O NanoStore aceita PNG, JPEG e WebP de ate 2 MB, valida e redimensiona a
imagem para no maximo 1600 x 1600 pixels e a exibe no menu lateral. O arquivo e
mantido em `instance/company`, fora do versionamento do Git.

O Caixa tambem oferece venda direta de balcao por leitor USB ou webcam. Cada
bip adiciona uma unidade, leituras repetidas somam quantidade e a conclusao
baixa o estoque, registra a venda e credita o pagamento no caixa aberto.
Em `Configuracao > HTTPS e camera`, o modo de leitura pode ser automatico,
leitor USB ou webcam. No automatico, dispositivos moveis mostram a acao de
camera e computadores mantem o foco preparado para o leitor USB. Navegadores
sem `BarcodeDetector` nativo usam o ZXing embarcado, sem depender de internet.

Na tela de Pedidos, o acompanhamento usa um kanban com as etapas `Novo`,
`Separado`, `Entrega` e `Delivery`. Os cards podem ser arrastados no desktop ou
movidos pelos botoes Anterior/Avancar no celular. O formulario do pedido tambem
abre um cadastro rapido de cliente e seleciona automaticamente o registro criado,
sem perder os itens que ja estavam sendo lancados.

Cada card possui a acao `Finalizar`. O pedido finalizado muda para o painel
verde `Finalizados hoje`, pode ser reaberto no mesmo dia e deixa o kanban
automaticamente no dia seguinte; pedidos ainda pendentes permanecem na fila.

Os pedidos do kanban podem ser editados ou excluidos. A edicao recalcula itens,
estoque e conta a receber, preservando pagamentos existentes; o novo total nao
pode ficar abaixo do valor ja recebido. A exclusao realiza cancelamento
auditavel, devolve os itens ao estoque, cancela a conta a receber e estorna os
pagamentos. Quando o recebimento pertence ao caixa aberto, ele deixa de compor o
saldo esperado; quando pertence a um caixa anterior, a devolucao e registrada
como saida no caixa atualmente aberto.

O menu da distribuidora comeca pelo `Dashboard`, que concentra os relatorios de
uso diario: saldo e atividade do caixa aberto, lista e totais de pedidos por
etapa, quantidade e valor de venda estimado do estoque, saldo por produto e
alertas de reposicao. Cada painel possui atalho para a operacao correspondente.

A area `Relatorios` oferece consultas de movimento de caixa, status de pedidos,
posicao consolidada e itens/lotes do estoque, entradas e saidas de caixa em
listas separadas e cadastro de clientes. As consultas aceitam busca e periodo,
alem de exportacao CSV e impressao do resultado visivel.

A aba `Estoque` apresenta a posicao atual por produto, valores de custo e venda,
filtros de disponibilidade, lotes ativos e movimentacoes recentes. A aba
`Documentacao` concentra os procedimentos de venda, cancelamento, correcoes
auditaveis, caixa, estoque, cadastros, entrega, faturamento e relatorios.

O cadastro de produtos e o lancamento de pedidos aceitam codigo de barras por
leitor USB (bipe seguido de Enter) ou pela webcam em navegador com HTTPS. No
cadastro, o codigo capturado preenche o novo produto; no pedido, um produto ja
cadastrado e localizado e adicionado imediatamente, somando a quantidade quando
o mesmo codigo e lido novamente. Codigos de barras duplicados sao rejeitados.
No celular, o botao de camera tambem oferece captura nativa por foto, seguindo o
mesmo fallback usado pelo RioB. Essa alternativa funciona mesmo quando a CA
privada nao foi aceita pelo aparelho; a imagem e processada localmente no
navegador pelo ZXing embarcado e nao e enviada ao servidor. A leitura continua
por video ainda exige HTTPS confiavel e permissao para a webcam.

Em `Cadastros > Produtos`, os itens existentes ficam disponiveis para busca e
edicao dos dados comerciais, estoque e tributacao. O indicador fiscal dessa
lista e uma validacao estrutural dos campos exigidos pelo NanoStore, nao uma
homologacao da Receita. A propria tela oferece acesso ao Classif da Receita
Federal para NCM e as consultas de GTIN e tabelas fiscais da SVRS; o
enquadramento final deve considerar regime tributario, UF e tipo da operacao.

O botao `Buscar item similar`, disponivel na inclusao e na edicao, compara nome,
codigo de barras, NCM e categoria com o catalogo ja cadastrado e tambem consulta
o Open Food Facts e a tabela NCM publica do Portal Unico Siscomex. Cada resultado
identifica sua origem. O catalogo externo pode preencher nome, marca, GTIN,
embalagem e unidade; a opcao fiscal escolhida separadamente preenche o NCM
oficial. Resultados internos reaproveitam os demais campos comerciais e fiscais,
sem duplicar a identidade do item. Os valores copiados continuam sujeitos a
conferencia, especialmente NCM, tributacao, beneficio fiscal e precos.

## Rodar localmente

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Depois abra `http://127.0.0.1:5000`.

## Docker com MySQL

```bash
docker compose up --build
```

Depois abra:

- `http://127.0.0.1:8080`
- `https://127.0.0.1:8443`

Para celular na mesma rede, abra pelo IP da maquina:

- `https://SEU_IP_LOCAL:8443`

Exemplo:

- `https://192.168.0.10:8443`

Configuracao importante para HTTPS por IP:

- defina `CERT_APP_HOSTS` no `.env` com o IP usado pelo celular
- exemplo: `CERT_APP_HOSTS=192.168.0.10`
- se trocar o IP ou adicionar dominio, force a reemissao com `CERT_FORCE_REISSUE=1` e suba novamente

Fluxo recomendado para liberar a camera no celular:

1. acesse `http://SEU_IP_LOCAL:8080/mobile-setup`
2. toque em `Baixar CA Android`
3. instale/confie o certificado CA no aparelho
4. depois toque em `Abrir NanoStore em HTTPS`

Quando o NanoStore estiver integrado ao portal NanoTechSoft, use o endereco do
portal (`https://192.168.200.254/apps/nanostore`). O HTTP na porta `5600`
permanece disponivel para baixar a CA antes do primeiro acesso HTTPS, e o proxy
TLS do portal atende na porta `443`.

Rotas leves para teste no celular:

- `GET /mobile-setup`
- `GET /healthz`

Endpoints de certificado disponiveis:

- `GET /api/ca/cert.pem`
- `GET /api/ca/cert.crt`
- `GET /api/app/cert.pem`
- `GET /api/app/cert.crt`

## Assistente de tributacao de produtos

No cadastro e na edicao do produto, o botao **Assistir tributacao** consulta o
CRT salvo em **Configuracao > Emitente fiscal**, apresenta CST ICMS ou CSOSN
compativeis com esse regime e completa somente campos estruturais seguros, como
CFOP padrao de venda interna, origem, unidade tributavel e `SEM GTIN` quando nao
ha codigo valido. O assistente nao escolhe automaticamente o enquadramento
tributario: CST/CSOSN, NCM, CEST e beneficios devem ser confirmados conforme a
operacao, a UF e a orientacao contabil.

Banco padrao do compose:

- host: `db`
- porta: `3306`
- database: `nanostore`
- user: `renan`
- password: defina em `MYSQL_PASSWORD`

Se o MySQL ja tiver sido iniciado antes com outro usuario ou senha, remova o volume antigo e suba novamente:

```bash
docker compose down -v
docker compose up --build
```

Se ainda aparecer `container nanostore-mysql is unhealthy`, veja o log do banco:

```bash
docker compose logs db
```

Para MySQL `8.4`, o parametro antigo `default-authentication-plugin=mysql_native_password` nao funciona mais. O projeto foi ajustado para usar `--mysql-native-password=ON`, que e o formato compativel com MySQL 8.4.

O container da aplicacao tambem inclui `cryptography`, necessario quando o MySQL usa autenticacao `caching_sha2_password`.

## Simulador de faturamento

O menu `Faturamento` gera XMLs locais vinculados as vendas e valida a assinatura
com a chave privada de um certificado A1. Esses arquivos usam um namespace
proprio, sao marcados como `semValorFiscal` e nunca sao transmitidos a SEFAZ.

O historico oferece a representacao branca em PDF A4 e o documento auxiliar em
bobinas de 58 mm ou 80 mm. Esses PDFs continuam identificados como simulacao sem
valor fiscal e nao incluem chave, QR Code ou protocolo de autorizacao ficticios.

## Dados de demonstracao da distribuidora

Na inicializacao, o cadastro idempotente inclui cinco mesas numeradas com nome e
localizacao e os produtos `TEST-GELO`, `TEST-CERVEJA`, `TEST-REFRIGERANTE` e
`TEST-CARVAO`, cada um com estoque de teste. Os NCMs e campos estruturais permitem
testar o fluxo, mas CST/CSOSN, CEST, CFOP, aliquotas e beneficios devem ser
confirmados pelo contador conforme CRT, UF, embalagem e operacao reais antes de
qualquer emissao fiscal de producao.

Pedidos podem ser abertos em PDF A4 ou como tiquete de 58 mm/80 mm pelo painel de
separacao e entrega. A impressao fisica e feita pelo dialogo do navegador, usando
escala de 100% e o tamanho de papel correspondente.

Configure o certificado somente por variaveis de ambiente:

```bash
NANOSTORE_FISCAL_CERT_PATH=/caminho/seguro/emitente.pfx
NANOSTORE_FISCAL_CERT_PASSWORD=senha-do-certificado
```

Certificados vencidos podem ser usados apenas para exercitar o simulador. Uma
integracao futura com homologacao deve exigir certificado vigente, cadastro
fiscal completo, schemas oficiais e bloqueio independente para producao.

Antes de gerar a simulacao, o modulo valida o emitente e os itens: CNPJ
compativel com o certificado, IE, UF, municipio IBGE, CRT, NCM, CEST quando
informado, CFOP de saida, origem, CST/CSOSN, PIS, COFINS, unidade e GTIN
tributaveis, cBenef para produto marcado com beneficio e os campos ANVISA/PMC
de medicamentos na NF-e. Para CRT 3 tambem exige CST IBS/CBS e cClassTrib.

Referencias oficiais usadas na implementacao:

- Portal Nacional da NF-e: Manual de Orientacao do Contribuinte 7.0
- Portal Nacional da NF-e: Notas Tecnicas 2021.004 e 2025.002
- Receita Federal: tabela NCM vigente
- Receita Estadual do Parana: tabela oficial de codigo de beneficio fiscal

O cadastro e o simulador fazem validacao preventiva. O calculo tributario e a
transmissao oficial ainda dependem de motor fiscal homologado, tabelas vigentes
e credenciamento/CSC da empresa na SEFAZ.

## VSCodium

O workspace inclui `.vscode/settings.json` para abrir o terminal integrado como `bash -l`, ajudando o `VSCodium` a herdar o `PATH` correto e encontrar comandos como `docker`.

Observacoes desta entrega:

- o container da aplicacao aguarda o MySQL ficar saudavel antes de subir
- os `selects` principais de operacao usam dados vindos do banco
- na tela de vendas o produto aparece em `select` e a tela mostra a lista de produtos com `quantidade` e `valor`
- o compose agora usa `nginx` + bootstrap de certificados, no mesmo estilo do projeto `RioBranco`
- a CA interna e o certificado HTTPS ficam no diretorio `./certs`
- para webcam no celular, o navegador precisa confiar na CA interna instalada no aparelho
- o fluxo de webcam conecta e exibe primeiro o video, antes de iniciar o leitor nativo ou ZXing
- quando a webcam nao estiver disponivel, o sistema esconde os botoes de scanner e mostra aviso com fallback manual
