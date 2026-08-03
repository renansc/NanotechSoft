# NanoStore

Projeto novo de gestao para farmacia, separado do `zap`, usando-o apenas como referencia arquitetural.

## O que esta pronto

- cadastro de categorias, fornecedores e produtos
- controle por lote, validade e localizacao
- vendas por balcao, WhatsApp, WooCommerce, WordPress, Mercado Livre e delivery
- faturamento individual e em massa com XML de simulacao assinado
- pagamentos com base para Pix e maquina de cartao
- configuracao de provedores e canais
- dashboard web inicial

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

Rotas leves para teste no celular:

- `GET /mobile-setup`
- `GET /healthz`

Endpoints de certificado disponiveis:

- `GET /api/ca/cert.pem`
- `GET /api/ca/cert.crt`
- `GET /api/app/cert.pem`
- `GET /api/app/cert.crt`

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
- quando a webcam nao estiver disponivel, o sistema esconde os botoes de scanner e mostra aviso com fallback manual
