# NF-e / Receita: Integracao e Operacao

## 1. Objetivo

Este documento explica:

- o que o sistema RioBranco suporta hoje na integracao de NF-e
- como configurar corretamente os modos `portal_assistido` e `certificado_digital`
- como validar se a integracao esta pronta
- quais testes fazer em homologacao ou producao
- o que ainda depende de acao manual do operador

## 2. Resumo honesto do suporte atual

Hoje o sistema suporta de forma operacional:

- configuracao central em `Config -> NF-e / Receita`
- modo `portal_assistido`, com abertura automatica da consulta publica ao bipar a chave
- modo `certificado_digital`, com consulta oficial via `NFeDistribuicaoDFe`
- leitura da chave de 44 digitos como fluxo principal no estoque, com consulta automatica no modo DF-e
- consulta de XML oficial pela chave de acesso impressa no DANFE
- sincronizacao por NSU (`distNSU`)
- manifestacao automatica de `Ciencia da Operacao` quando configurada
- importacao da NF-e no estoque a partir de XML manual ou XML obtido via DF-e
- importacao da NF-e em abastecimentos a partir de XML manual ou XML obtido via DF-e
- bloqueio opcional de notas duplicadas no estoque e no abastecimento
- status da integracao NF-e no painel `Config -> Status`

Hoje o sistema **nao** executa:

- bypass de reCAPTCHA no portal publico
- automacao do portal publico depois que ele abre no navegador
- leitura automatica do resultado da pagina da Receita apos a consulta manual

Em outras palavras:

- no `portal_assistido`, o sistema abre o portal, mas nao recebe automaticamente o XML depois
- no `certificado_digital`, o sistema usa o fluxo oficial DF-e para buscar XML e sincronizar NSU
- no estoque, PDF e XML ficam como contingencia; a operacao principal deve ser a chave bipada

## 3. Mudancas recentes desta area

As mudancas recentes que impactam a operacao com NF-e foram:

- campos novos de configuracao: ambiente, UF autora, senha do certificado, ultimo NSU e manifestacao automatica
- status detalhado da NF-e em `Config -> Status`
- diagnostico da integracao dentro de `Config -> NF-e`
- sincronizacao oficial DF-e por `NFeDistribuicaoDFe`
- consulta do XML oficial pela chave impressa no DANFE
- manifestacao automatica de `Ciencia da Operacao`
- importacao de estoque via DF-e
- importacao de abastecimento via DF-e

## 4. Onde configurar

Tela principal:

1. Abrir `RioBranco.html`
2. Entrar em `Config`
3. Abrir a subaba `NF-e`

Campos disponiveis hoje:

- `Ativar integracao NF-e`
- `Modo de integracao`
- `Ambiente SEFAZ`
- `Ao bipar a chave, abrir automaticamente o portal oficial`
- `Bloquear notas duplicadas no estoque e no abastecimento`
- `Manifestar Ciencia da Operacao automaticamente quando vier somente resumo`
- `URL oficial da consulta publica da NF-e`
- `CNPJ do destinatario`
- `UF autora do destinatario`
- `Caminho do certificado digital (.pfx/.p12)`
- `Senha do certificado digital`
- `Ultimo NSU sincronizado`

## 5. Significado de cada campo

### 5.1 `Modo de integracao`

- `portal_assistido`: abre a consulta publica no navegador
- `certificado_digital`: usa o fluxo oficial DF-e no backend

### 5.2 `Ambiente SEFAZ`

- `producao`: usar para notas reais
- `homologacao`: usar apenas para ambiente e notas de teste

Se a nota e real, usar `homologacao` vai impedir a integracao.

### 5.3 `CNPJ do destinatario`

Deve ser o CNPJ da empresa destinataria das NF-e e dona do certificado digital.

### 5.4 `UF autora do destinatario`

Sigla da UF da empresa destinataria.

Exemplos:

- `AC`
- `SP`
- `MG`

### 5.5 `Caminho do certificado digital`

Em Docker, o diretorio `./certs` do projeto e montado em `/app/certs` dentro do container.

Exemplo pratico:

- arquivo no host: `certs/BEBIDAS_123456.pfx`
- caminho dentro do app: `/app/certs/BEBIDAS_123456.pfx`

### 5.6 `Senha do certificado digital`

E a senha real do arquivo `.pfx` ou `.p12`.

Ela nao fica em arquivo `.env`; e salva na configuracao NF-e do sistema.

### 5.7 `Ultimo NSU sincronizado`

- no primeiro teste, pode ficar vazio
- depois das sincronizacoes, o sistema atualiza esse valor automaticamente

### 5.8 `Manifestar Ciencia da Operacao automaticamente`

Quando marcado:

- se a SEFAZ retornar apenas resumo da NF-e
- o sistema tenta registrar `Ciencia da Operacao`
- depois consulta novamente o DF-e para obter o XML completo

## 6. Modos suportados

### 6.1 `portal_assistido`

Comportamento real:

- o sistema salva a URL oficial configurada
- ao bipar uma chave valida de 44 digitos, o frontend pode abrir essa URL no navegador
- o operador resolve o reCAPTCHA manualmente no portal oficial
- depois disso, o XML oficial continua sendo o insumo esperado para importacao no RioBranco

Importante:

- abrir o portal e resolver o reCAPTCHA **nao** faz a nota entrar sozinha no sistema
- depois do portal, ainda e preciso obter o XML oficial e importar manualmente

Quando usar:

- quando a operacao ainda depende de consulta humana no portal oficial
- quando o cliente nao quer usar certificado digital ainda
- como apoio operacional de consulta, nao como automacao completa

### 6.2 `certificado_digital`

Comportamento real hoje:

- o sistema usa `NFeDistribuicaoDFe`
- pode consultar XML oficial pela chave de acesso
- pode sincronizar notas por NSU
- pode manifestar `Ciencia da Operacao`
- pode entregar a NF-e direto para o fluxo de estoque ou abastecimento

Quando usar:

- quando o cliente recebe DANFE impressa e nao tem o XML em maos
- quando quer automatizar a obtencao do XML oficial
- quando quer sincronizacao backend pelo fluxo oficial da SEFAZ

## 7. Passo a passo de configuracao recomendada

### 7.1 Etapa 1: habilitar a integracao

1. Abrir `Config -> NF-e`
2. Marcar `Ativar integracao NF-e`
3. Escolher o modo inicial
4. Salvar

### 7.2 Etapa 2: configurar `portal_assistido`

1. Selecionar `Portal assistido`
2. Confirmar a `URL oficial da consulta publica da NF-e`
3. Definir se `Ao bipar a chave, abrir automaticamente o portal oficial` deve ficar ativo
4. Definir se `Bloquear notas duplicadas` deve ficar ativo
5. Salvar

Resultado esperado:

- ao bipar uma chave valida, o portal oficial pode abrir no navegador
- `Config -> Status` passa a mostrar portal pronto ou pendencias de configuracao

### 7.3 Etapa 3: configurar `certificado_digital`

1. Selecionar `Certificado digital / DF-e`
2. Preencher `Ambiente SEFAZ`
3. Preencher `CNPJ do destinatario`
4. Preencher `UF autora`
5. Informar o caminho do `.pfx` ou `.p12`
6. Informar a senha do certificado
7. Deixar `Manifestar Ciencia da Operacao automaticamente` marcado, salvo excecao operacional
8. Deixar `Ultimo NSU` vazio no primeiro teste
9. Salvar

Exemplo em Docker:

- `Ambiente`: `producao`
- `CNPJ do destinatario`: `12345678000199`
- `UF autora`: `AC`
- `Caminho do certificado`: `/app/certs/BEBIDAS_123456.pfx`
- `Senha do certificado`: senha real do certificado
- `Ultimo NSU`: vazio

Resultado esperado:

- `Config -> Status` passa a mostrar se o DF-e esta pronto ou pendente
- `Config -> NF-e` passa a mostrar diagnostico da integracao

## 8. Como saber se a integracao esta pronta

### 8.1 `Config -> Status`

O bloco de NF-e passa a exibir:

- modo ativo
- ambiente e UF
- tipo de consulta
- politica de duplicidade
- resumo de configuracao
- pendencias encontradas

### 8.2 `Config -> NF-e`

Os textos de apoio mostram:

- diagnostico atual da integracao
- se o DF-e esta pronto ou pendente
- se o certificado foi localizado
- se ha dependencias faltando no backend

## 9. Passo a passo operacional

### 9.1 Estoque com XML manual

1. Abrir `Estoque`
2. Bipar a chave se quiser validacao adicional
3. Selecionar o arquivo XML ou PDF
4. Clicar em `Ler XML/PDF de contingencia`
5. Revisar a confirmacao
6. Confirmar a importacao
7. Consolidar a conferencia no almoxarifado

Observacao:

- se o arquivo enviado for PDF e a chave estiver presente, o sistema tenta buscar o XML oficial via DF-e antes de usar a leitura aproximada do PDF

### 9.2 Estoque via DF-e

1. Abrir `Estoque`
2. Bipar ou digitar a chave de 44 digitos
3. Se o modo estiver em `certificado_digital`, a busca inicia automaticamente ao terminar a leitura da chave
4. Se preferir, usar o botao `Buscar NF-e pela chave (DF-e)` para repetir a consulta manualmente
5. Revisar a confirmacao
6. Confirmar a importacao

### 9.3 Abastecimento com XML manual

1. Abrir `Gestao de Frota`
2. Localizar um abastecimento `liberado`
3. Informar a chave, se desejar
4. Selecionar o XML
5. Clicar em `Importar XML`

### 9.4 Abastecimento via DF-e

1. Abrir `Gestao de Frota`
2. Localizar um abastecimento `liberado`
3. Informar a chave de acesso
4. Clicar em `Buscar DF-e`

## 10. Testes recomendados

### 10.1 Teste pela interface

Em `Config -> NF-e`:

1. Salvar a configuracao
2. Clicar em `Sincronizar DF-e`
3. Verificar a mensagem retornada

Em `Estoque`:

1. Informar uma chave real de 44 digitos
2. Clicar em `Buscar XML pela chave (DF-e)`

### 10.2 Teste por API

Consultar configuracao:

```bash
curl -sk https://SEU_HOST:8443/api/nfe/config
```

Sincronizar DF-e:

```bash
curl -sk -X POST https://SEU_HOST:8443/api/nfe/df-e/sincronizar \
  -H "Content-Type: application/json" \
  -d '{}'
```

Testar uma chave no estoque:

```bash
curl -sk -X POST https://SEU_HOST:8443/api/estoque/nfe/preview_dfe \
  -H "Content-Type: application/json" \
  -d '{"chave_acesso":"CHAVE_COM_44_DIGITOS"}'
```

### 10.3 Teste no container

Ver se o front novo esta no container:

```bash
docker compose exec app sh -lc "grep -n 'nfeConfigAutoManifestarCiencia' /app/RioBranco.html"
docker compose exec app sh -lc "grep -n 'preview_dfe' /app/server.py"
```

Ver logs:

```bash
docker compose logs -f app
```

## 11. Erros comuns

### 11.1 O portal abre, mas nada entra no sistema

Causa comum:

- o sistema esta em `portal_assistido`

Explicacao:

- nesse modo, abrir o portal e o comportamento esperado
- depois do reCAPTCHA, o sistema nao importa nada sozinho

Acao:

- obter o XML oficial manualmente
- ou usar `certificado_digital` para fazer a consulta oficial via DF-e

### 11.2 O modo DF-e nao faz nada

Causas comuns:

- integracao NF-e desativada
- CNPJ do destinatario vazio ou invalido
- UF autora vazia
- certificado nao encontrado no caminho configurado
- senha do certificado nao preenchida
- ambiente errado (`homologacao` para nota real)
- dependencias Python do DF-e nao instaladas no container

Acao:

- revisar `Config -> Status`
- revisar o diagnostico em `Config -> NF-e`
- conferir o caminho do certificado dentro do container
- confirmar se a chave bipada tem 44 digitos
- acompanhar a mensagem em `Estoque -> NF-e automatica pela chave`, porque agora o status da busca aparece ali

### 11.3 O certificado esta no host, mas o app nao encontra

Causa comum:

- foi informado o caminho do host, e nao o caminho interno do container

Acao:

- se o arquivo estiver em `certs/BEBIDAS_123456.pfx`
- usar `/app/certs/BEBIDAS_123456.pfx`

### 11.4 A senha do certificado nao aparece na tela

Causa comum:

- navegador com cache antigo
- container `app` ainda com front antigo

Acao:

- recriar `app` e `proxy`
- fazer `Ctrl+F5` ou abrir em janela anonima
- conferir o HTML dentro do container

### 11.5 Nota duplicada

Causa comum:

- a mesma nota ja foi usada antes

Acao:

- revisar `Bloquear notas duplicadas`
- localizar a conferencia ou abastecimento anterior antes de repetir a operacao

## 12. Checklist rapido de homologacao

1. `docker compose up -d --build`
2. Verificar se o certificado existe em `/app/certs/...`
3. Confirmar se `Config -> NF-e` esta mesmo em `ambiente=homologacao`
4. Se a base veio de `sync-production-to-homolog.sh`, revisar porque o script agora desativa a integracao e limpa `ultimo_nsu` por seguranca
5. Abrir `Config -> NF-e`
6. Salvar a configuracao completa
7. Verificar `Config -> Status`
8. Clicar em `Sincronizar DF-e`
9. Testar `Buscar XML pela chave (DF-e)` no estoque

## 13. Referencias internas do projeto

Para contexto complementar, ler tambem:

- `OPERACAO_E_DEPLOY.md`
- `API_E_DADOS.md`
- `ARQUITETURA_SISTEMA.md`

Pontos do sistema relacionados a este guia:

- tela `Config -> NF-e / Receita`
- bloco `Config -> Status -> NF-e`
- secao `Estoque -> Importar NF-e`
- acao `Buscar DF-e` na grade de abastecimentos
