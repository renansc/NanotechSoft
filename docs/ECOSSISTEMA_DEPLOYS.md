# Ecossistema de código e deploys

O GitHub é a fonte central do ecossistema, mas componentes com ciclos e dados
distintos mantêm repositórios próprios. A matriz versionada em
`deploy/ecosystem.json` define qual componente e perfil pertencem a cada
ambiente.

## Componentes oficiais

- **Portal e apps NanotechSoft:** `renansc/NanotechSoft`, branch `main`.
- **PACS principal:** `renansc/RisPacsFull`, branch `main`.

O PACS do Laboratório Santa Terezinha é a implementação principal. Ele não deve
ser copiado para dentro de `apps/pacs`; o portal o apresenta como módulo externo
pela variável local `LABORATORIO_PACS_URL`. Assim não existem duas cópias do
PACS evoluindo separadamente.

## Matriz operacional

| Deploy | Componente | Política |
| --- | --- | --- |
| Rio Branco | Portal, perfil `rio-branco` | somente módulos contratados |
| Nanotech | Portal, perfil `nanotech` | todos os apps publicados e PACS externo |
| Laboratório | PACS | somente a stack do `RisPacsFull` |
| Senhor | Portal, perfil `senhor` | NanoStore; atualizar somente após 18h |
| Render | Portal, perfil `render` | cache em nuvem somente leitura e atalho web externo para o PACS |

Endereços, usuários, senhas, chaves SSH e arquivos `.env` são configuração
local e nunca entram nessa matriz ou no Git.

No Render, `LABORATORIO_PACS_URL` deve apontar para a publicacao HTTPS do
cockpit PACS. O portal apenas entrega o link ao navegador: nao faz proxy, nao
entra na Tailscale e nao recebe banco, exames ou imagens do laboratorio.

## Regras que evitam conflito entre clientes

1. Remover um módulo do contrato de um cliente não remove seu código global.
2. O portal valida o contrato no servidor; uma URL direta não libera app fora
   do perfil, nem para administrador.
3. O perfil Nanotech possui uma lista mínima de módulos obrigatórios. A
   validação de publicação falha se um desses manifests desaparecer.
4. Dados, bancos, exames, imagens, anexos e backups nunca são distribuídos pelo
   Git.
5. Cada atualização usa o comando do componente indicado na matriz. Atualizar
   código não autoriza restore, migração ou sincronização de banco.
6. O update local encerra serviços RioB quando o perfil não os possui e remove
   containers órfãos do mesmo projeto, sem apagar volumes ou bancos.

## Fluxo de publicação

No Portal, valide e publique pela raiz:

```bash
./up.sh
./git-safe-push.sh -m "descricao"
```

No PACS principal, use os comandos do próprio repositório:

```bash
./scripts/deploy/publish-git.sh -m "descricao"
./scripts/deploy/update.sh
```

Nos destinos, o update ocorre no repositório do componente e na branch `main`.
O deploy Senhor deve respeitar a janela versionada após 18h no fuso
`America/Sao_Paulo`.

## Selecao do ambiente pelos comandos

`up.sh`, `down.sh`, `update.sh` e `git-safe-push.sh` continuam sendo os unicos
comandos publicos, com a mesma sintaxe. Todos leem `NANOTECH_ENV_FILE`, quando
definido, ou o primeiro arquivo existente entre `.env` e `.env_local` no checkout.
Seletores do terminal prevalecem. O arquivo e interpretado como dados, sem
executar comandos de shell, e o Compose recebe esse mesmo arquivo.

Perfil, cliente e modo devem concordar. Antes de operar servicos, os comandos
conferem o cliente do container do portal existente e recusam operar outro
cliente. Nomes de servicos, containers e volumes existentes sao mantidos.
Os perfis representam deploys independentes; trocar uma variavel nao migra nem
converte um deploy existente. O padrao legado sem seletores e `rio-branco`.

No perfil Render (tambem reconhecido por `CLIENTE_DEPLOY_ID=cloud`), os comandos
locais de Docker sao bloqueados: o deploy usa o Blueprint. O Git seguro ignora
Compose nesse perfil, mantendo as validacoes de codigo e a protecao de dados.
Nos demais perfis, o Git seguro valida somente os servicos do ambiente selecionado.

`up.sh` inicia o banco local com `--no-recreate`; `down.sh` nao para bancos;
`update.sh` nao os opera. Nao ha restore, copia ou sincronizacao de dados nesses
fluxos. `--only` no Git seguro verifica cada arquivo dentro dos diretorios pedidos,
incluindo arquivos ja versionados. Dados de runtime nunca acompanham os PDFs
tecnicos versionados de Automacao. Testes em `tests/test_deploy_commands.py`
usam ambientes temporarios e servicos simulados, sem parar clientes reais.
