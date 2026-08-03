# Manual permanente de pesquisa para IA

Este documento é a fonte de verdade operacional do NanotechSoft. Deve ser lido
antes de qualquer mudança, independentemente do modelo, versão ou fornecedor da
IA. Quando código e documentação divergirem, a IA deve investigar e corrigir a
divergência; não deve criar um segundo fluxo concorrente.

## Pesquisa obrigatória antes de alterar

1. Leia `AGENTS.md`, este manual e o `README.md`.
2. Localize o app em `apps/<app>/app.json` e confirme seu `source_dir`.
3. Pesquise implementações existentes com `rg` antes de criar arquivos, rotas,
   tabelas, telas ou scripts.
4. Consulte a documentação específica do app. Para o RioB, comece por
   `apps/riob/source/docs/AI_CONTEXT.md`.
5. Confira `git status --short` e preserve alterações e arquivos do usuário.
6. Valide a mudança no menor escopo possível antes de publicar.

## Arquitetura pressuposta

- A raiz do repositório é o ponto operacional único.
- O `docker-compose.yml` da raiz descreve portal, RioB, proxies e bancos usados
  no desenvolvimento integrado.
- O portal é o único responsável pela autenticação. O RioB não possui nem deve
  voltar a possuir tela, sessão ou fluxo próprio de login.
- Usuários comuns visualizam somente os apps liberados no portal.
- Apps embarcados, inclusive RioB, devem receber e respeitar o tema do portal.
- Código de app fica em `apps/<app>/source`; dados de execução, credenciais,
  backups, anexos e bancos não devem ser versionados.

## Comandos canônicos

Existem somente quatro comandos operacionais públicos, todos na raiz:

```bash
./up.sh
./down.sh
./update.sh
./git-safe-push.sh -m "mensagem"
```

Não criar cópias desses scripts dentro de `apps/`, aliases sem extensão ou
variantes como `deploy-no-ai.sh`. A implementação compartilhada pode permanecer
em `deploy/`, mas o operador sempre chama os arquivos da raiz.

### `up.sh`

- Uso: testar alterações locais.
- Reconstrói e sobe portal e RioB.
- Pode iniciar bancos locais que ainda estejam parados.
- Nunca apaga volumes, restaura backup ou sincroniza produção/homologação.
- `NO_CACHE=1 ./up.sh` força build sem cache.

### `down.sh`

- Uso: encerrar o teste das aplicações.
- Para portal, RioB e proxy do RioB.
- Não para, remove, recria, restaura nem sincroniza bancos.
- Não usa `docker compose down` e não remove volumes.

### `update.sh`

- Uso: atualizar produção a partir do Git.
- Executa `git pull --ff-only`, relê o próprio script quando ele mudar,
  reconstrói e recria somente portal e RioB.
- Não inicia, para, restaura, importa, exporta ou sincroniza banco.
- Não chama rotinas de restore nem scripts de migração operacional.
- Alterações idempotentes de schema executadas pela própria aplicação durante
  o startup são parte do código da aplicação, não do script de update.

### `git-safe-push.sh`

- Uso: validar, criar commit e enviar automaticamente a branch atual ao GitHub.
- Neste projeto, o envio ao `origin` por Git/SSH esta previamente autorizado;
  nao exigir GitHub CLI (`gh`) quando o remoto SSH estiver funcional. Use o
  script canonico e respeite o escopo explicitamente autorizado pelo usuario.
- Deve bloquear `.env`, credenciais, backups, dados de runtime e outros arquivos
  sensíveis.
- Com worktree misto, use `--only CAMINHO` repetidamente.
- Use `-y` quando quiser confirmar commit e push sem pergunta interativa.
- Quando Docker estiver indisponível, use `--skip-compose`; as validações locais
  restantes continuam obrigatórias.
- Nunca usar `git add -A` fora das proteções do script para contornar bloqueios.

## Banco de dados: regra de não interferência

Os bancos e volumes são persistentes. Operações comuns de subir, parar,
atualizar ou publicar código não autorizam:

- apagar ou recriar volumes;
- restaurar backups;
- copiar produção para homologação;
- copiar homologação para produção;
- executar `docker compose down -v`;
- trocar credenciais ou apontamentos de ambiente.

Backup, restore, sincronização e migração de dados são operações separadas e
exigem pedido explícito do usuário.

## RioB

- Frontend principal: `apps/riob/source/RioBranco.html`, `script.js` e
  `style.css`.
- Backend: `apps/riob/source/server.py`.
- O módulo Comissões é um workflow de primeiro nível. Sua tela principal lista
  lançamentos e “Novo lançamento” abre um popup completo por abas.
- Mudanças de banco devem ser retrocompatíveis e idempotentes.
- O frontend é servido sem cache pelo backend; se uma mudança não aparecer,
  confirme commit/push, branch, imagem reconstruída e o comando canônico antes
  de atribuir o problema ao navegador.

## Publicação e diagnóstico

Antes de afirmar que uma versão foi implantada, confirme:

```bash
git status --short
git log -1 --oneline
git rev-parse HEAD
git rev-parse origin/main
```

Na produção, `update.sh` só pode receber código já enviado ao remoto. Executar
`up.sh` ou `update.sh` em outra máquina não inclui alterações locais sem commit.

Ordem normal:

```bash
./up.sh
./git-safe-push.sh -m "descrição objetiva"
# na produção
./update.sh main
```

## Critério para remover código

Antes de excluir, pesquise todas as referências. Remova duplicações comprovadas
e atualize chamadas/documentação no mesmo trabalho. Não remova dados do usuário,
backups ou arquivos não relacionados. Código legado sem chamadas ainda deve ser
avaliado quanto a entrada externa antes da exclusão.

## Portas do Portal no Docker e no Render

- A imagem do Portal deve escutar a variável `PORT` fornecida pelo ambiente.
- Quando `PORT` não estiver definida, o padrão local obrigatório é `5600`, conforme o `docker-compose.yml`.
- Nunca fixe `10000` diretamente no `Dockerfile`: essa é a porta atualmente usada pelo Render e uma constante nela interrompe o healthcheck e o acesso local.
- Alterações de inicialização devem ser validadas tanto pelo `./up.sh` local quanto pela configuração do `render.yaml`.
- No Render, prefira `RIOB_BASE_URL` apontando para uma origem HTTPS externa: o
  Portal deve funcionar como proxy reverso e manter a URL pública do Render no
  navegador. O subprocesso no mesmo contêiner é somente compatibilidade.
- No compose local, o RioB permanece no serviço `riob-app`.
- Cache e balanceamento não podem incluir respostas mutáveis, sessões, uploads
  ou APIs de escrita sem armazenamento e afinidade compartilhados entre todas
  as origens.
