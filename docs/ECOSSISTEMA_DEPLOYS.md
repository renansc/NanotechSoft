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
| Render | Portal, perfil `render` | cache em nuvem somente leitura |

Endereços, usuários, senhas, chaves SSH e arquivos `.env` são configuração
local e nunca entram nessa matriz ou no Git.

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
