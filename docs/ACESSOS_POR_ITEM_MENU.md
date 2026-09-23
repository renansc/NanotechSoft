# Acessos por item do menu

Em **Configurar > Usuarios e acessos**, selecionar uma pessoa e marcar ou
desmarcar cada destino do menu. **Salvar usuario** grava as escolhas. A busca
filtra por nome da tela, modulo ou categoria. O controle vale para usuarios
comuns; administradores continuam com acesso integral. Usuarios e acessos,
Clientes e modulos e Backup do portal continuam exclusivos de administrador,
identificados dessa forma na lista.

A tela ocupa toda a largura disponivel. Os dados do usuario se adaptam de quatro
colunas no desktop para uma no celular; as permissoes aparecem em grupos por
modulo, com colunas conforme o espaco. A busca oculta os grupos sem resultados,
e a barra de salvar/excluir permanece acessivel durante a rolagem. Este ajuste
de apresentacao preserva o catalogo e as regras de autorizacao descritos abaixo.

O perfil Rio Branco possui 137 controles: RioB (71), Zap (16), Tecnologia (12),
Automacao (11), Email (10), XML (6), Sistema (6) e Chamados (5).
O [mapa completo](MAPA_ACESSOS_MENU.csv) identifica categoria, nome, destino,
chave individual e recurso anterior. Atalhos repetidos para o mesmo destino
compartilham um controle; as categorias aparecem juntas. Cada destino distinto
possui sua propria escolha, mesmo quando antes compartilhava uma permissao.

Exemplo: **Monitoramento de backups**, **Planos de backup** e **Instalar agentes
de backup** podem ser liberados separadamente. Desmarcar Instalar agentes
bloqueia esse destino mesmo se a permissao geral `tecnologia:backup` ou `*`
continuar marcada. A mesma regra vale para os demais itens.

## Implementacao e compatibilidade

- Gestao > Tecnologia > Rede possui o recurso `tecnologia:rede` e escolha
  individual propria; `GET /apps/tecnologia/api/network` e `/network/<id>`
  respeitam essa escolha, inclusive bloqueios sobre `*`. Nao libera cadastro,
  sondas manuais ou outras telas, nem concede acessos automaticamente.
- `menu_access.py` deriva os controles dos `menu_groups` e `config_groups` do
  perfil ativo nos manifests. `portal.app.json` inclui os itens comuns do sistema.
- A chave `menu:<hash>` usa o destino normalizado, com os seletores de tarefa
  (`view`, `secao`, `painel`, `visao` e fragmento). Renomear ou mover o item entre
  categorias preserva a chave. Mudar seu destino exige revisar compatibilidade.
- A tabela existente `usuario_app_permissoes` guarda `permitido=1` para liberar
  e `permitido=0` para bloquear. O bloqueio individual prevalece sobre os recursos
  gerais. Sem escolha individual gravada, vale a regra anterior do recurso.
- `GET /api/usuarios` retorna `catalogo_acessos[].menus` e
  `usuarios[].permissoes_menu`. `POST/PUT /api/usuarios` aceita
  `permissoes_menu: {app_key: {chave_do_menu: true|false}}`. Omitir esse campo
  preserva todas as escolhas; enviar parte dele altera somente as chaves enviadas.
  Chaves desconhecidas e valores que nao sejam booleanos sao rejeitados.
- O payload anterior `permissoes` continua disponivel. As permissoes gerais e
  acoes internas existentes aparecem em uma secao recolhida. A atualizacao do
  codigo nao grava nem amplia concessoes. Salvar o formulario grava explicitamente
  as escolhas mostradas para a pessoa selecionada.
- O menu, a entrada inicial e o servidor consultam as escolhas. Rotas de paginas
  e APIs mapeadas em `api_destinations` validam a tarefa antes do encaminhamento.
  APIs de leitura compartilhadas podem atender varias telas liberadas; isso nao
  libera a escrita de uma tela irma. A autorizacao anterior continua nas rotas
  sem mapeamento individual e nas acoes internas, como finalizar contagem.
- Fragmentos `#...` nao chegam ao servidor HTTP. `static/menu-access.js` bloqueia
  a tela no navegador e suas transicoes; o servidor verifica as APIs associadas.
  RioB recebe o mesmo bloqueio dentro do frame. O atalho antigo `#backup` de
  Tecnologia corresponde a `#backup-visao`.
- Sessao unica, contrato do deploy, operacoes exclusivas de administrador e modo
  somente leitura da nuvem permanecem obrigatorios.

Este cadastro controla itens de menu. Botoes e operacoes internas continuam
vinculados a suas telas e as restricoes existentes.

## Manutencao e verificacao

Gestao > Tecnologia > Rede possui a acao interna **Buscar dispositivos**, com
recurso proprio `tecnologia:rede_scan` no catalogo de Config > Usuarios e acessos.
Exige tambem acesso ao item Rede; o bloqueio individual de Rede prevalece sobre
a concessao da acao. O POST `network/scan` somente consulta a rede privada local,
nao cadastra nem monitora resultados e e bloqueado no Render. A concessao nao e
automatica; administradores/acesso integral preservam as regras existentes.

Ao alterar um menu, atualizar seu manifest, documentacao e, quando houver novas
APIs, o relacionamento com a tela no servidor. Gerar o mapa com
`python3 tools/audit_navigation.py`; o inventario de rotas permanece em
`AUDITORIA_ROTAS_RIO_BRANCO.csv`.

- `tests/test_individual_menu_access.py`: cobertura dos itens, bloqueio com `*`,
  liberacao isolada, URLs diretas, APIs, leitura compartilhada, persistencia e
  validacao do payload, configuracoes em lote do Zap.
- `tests/check_individual_menu_access.py`: formulario real com dados sinteticos,
  137 controles, busca, salvar/recarregar e fragmentos em desktop e celular.
- `tests/check_module_tasks.py`: telas reais e dependencias de Tecnologia com
  somente um item liberado, alem da navegacao dos tres modulos.

As verificacoes de escrita usam fixtures; nao alteram permissoes de contas reais.

## Aplicacao local — 21/09/2026

Aplicado pelo comando canonico `./up.sh`, com portal saudavel e proxies
atualizados. A verificacao HTTPS confirmou os 137 controles em Usuarios e
acessos, a correspondencia dos links do menu com o catalogo, a busca por backup
e monitoramento de link e as telas relacionadas. Os sete arquivos de codigo
conferidos no container possuem o mesmo SHA-256 do workspace.

Resultado: 83 testes unitarios aprovados; formulario verificado em desktop e
celular, bloqueio dentro do frame RioB e 54 visitas as telas dos tres modulos.
Permissoes de contas reais nao foram alteradas. Esta aplicacao e local.
