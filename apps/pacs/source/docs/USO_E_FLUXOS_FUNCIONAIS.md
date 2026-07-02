# Uso e Fluxos Funcionais

## 1. Visao pratica do cockpit

O menu lateral do raioXPacs foi desenhado para concentrar o trabalho da clinica em um unico cockpit. A leitura mais
util deste documento e pensar em **qual tela usar em cada fase do exame**.

## 2. Menu a menu

## 2.1 Dashboard

Use para leitura rapida do estado da operacao:

- cards de resumo;
- contadores do pipeline operacional;
- ultimos exames;
- ultimas mensagens;
- chamadas.

Indicado para:

- inicio do expediente;
- monitoramento de gargalos;
- validacao rapida depois de sincronizacoes ou mudancas de status.

## 2.2 Kanban

O Kanban mostra o fluxo radiologico por coluna e permite arrastar exames entre etapas permitidas.

Use quando a equipe precisa:

- visualizar fila e gargalos;
- mover exames manualmente entre etapas;
- acompanhar bloqueios de transicao;
- ver rapidamente quais exames ja podem ir para laudo.

Boas praticas:

- use o Kanban para gestao visual;
- confirme detalhes do exame nas telas `Exames` e `Laudos & Viewer`;
- respeite mensagens de bloqueio quando um exame nao puder ser movido manualmente.

O botao `Sincronizar PACS` recalcula os espelhos locais, compara a worklist da aplicacao com o PACS e atualiza o status dos exames sem exigir refresh manual.

## 2.3 Pacientes

Tela de cadastro basico do paciente:

- nome;
- data de nascimento;
- sexo;
- CPF;
- telefone;
- email;
- observacoes.

Fluxo normal:

1. cadastrar ou localizar o paciente;
2. revisar CPF e contato;
3. seguir para `Exames`.

## 2.4 Exames

E o centro operacional do cadastro clinico. Aqui a equipe:

- cadastra e edita procedimentos;
- usa a busca rapida por nome para localizar um procedimento cadastrado;
- monta um exame;
- ajusta agenda, modalidade, estacao/AET e medicos;
- define preco;
- publica ou retira da worklist local;
- abre o workspace do exame.

Quando usar:

- recepcao: criar ou editar o exame;
- tecnico: revisar agenda, modalidade e estacao;
- supervisao: confirmar se o status de MWL e fluxo esta coerente.

## 2.5 Laudos & Viewer

Essa tela cobre tres frentes:

- fila para laudo;
- visualizacao de anexos e objetos DICOM;
- edicao do laudo medico e upload de anexos.

Fluxo tipico:

1. abrir o workspace do exame;
2. revisar anexos e objetos DICOM;
3. preencher titulo, achados e impressao diagnostica;
4. salvar laudo;
5. liberar o viewer/compartilhamento quando necessario.

Observacoes:

- com laudo completo, o exame tende a evoluir para `Finalizado`;
- anexos podem ser imagens web ou arquivos DICOM;
- o link `Viewer / Compartilhar` abre a experiencia de visualizacao externa do exame.

## 2.6 Financeiro

Mostra resumo financeiro e faturas derivadas dos exames.

Use para:

- acompanhar quantidade de faturas;
- ver total aberto e total pago;
- marcar pagamentos manualmente;
- cruzar exame, procedimento e faturamento.

## 2.7 Relatorios

O menu `Relatorio` abre uma lista de modelos prontos para consulta rapida:

- resumo financeiro;
- por convenio;
- por paciente.

Use quando precisar:

- filtrar por dia ou mes;
- restringir por convenio;
- escolher um paciente em um select do banco;
- abrir o PDF em nova aba sem depender de ferramentas pesadas;
- acompanhar os totais tambem no dashboard.

O fluxo foi pensado para ser leve: a geracao usa consulta SQL direta e um PDF simples, sem camadas extras de renderizacao.

## 2.8 Comunicacao

Concentra:

- tela de login por departamento;
- chat entre departamentos;
- departamentos predefinidos para recepcao, sala de raiox e ultrassom;
- mensagens nao lidas por setor.

Uso recomendado:

- o departamento exibido vem do login e nao precisa ser digitado;
- escolha o setor de destino na lateral;
- envie mensagens curtas e objetivas para coordenacao interna.

## 2.9 Cameras

A funcao de cameras nao faz parte da interface atual.

Se o ambiente ainda tiver codigo legado para camera runtime, isso fica fora do fluxo operacional do cockpit atual.

## 2.10 Painel

Usado para organizar a chamada de pacientes e exibir a TV/painel publico.

A tela cobre:

- configuracao do titulo, subtitulo e video;
- destinos de chamada;
- fila atual e historico;
- disparo de chamada;
- tela cheia para uso como painel.

Fluxo tipico:

1. recepcao ou operador confirma o destino exibido;
2. envia a chamada;
3. o painel exibe a senha/chamada;
4. a fila e o historico sao atualizados.

## 2.11 Worklist

Mostra dois lados da operacao:

- fila local de exames elegiveis/publicados;
- espelho da worklist PACS.

Serve para:

- verificar se a publicacao local aconteceu;
- comparar o que a clinica entende como ativo com o que a MWL esta servindo;
- remover exames da fila quando necessario.

O botao `Sincronizar PACS` tambem ajuda a trazer para a tela os ajustes de status vindos do PACS local ou externo, o que e util quando a conexao de homologacao e diferente da maquina local.

## 2.12 Storage

Tela operacional de infraestrutura:

- uso de disco;
- contadores do PACS;
- resumo de backups;
- botoes para gerar backup de banco e imagens;
- lista de arquivos gerados.

Essa tela deve ser usada antes de:

- deploys mais arriscados;
- mudancas grandes de configuracao;
- limpeza ou manutencao do runtime.

## 2.13 Config

Centraliza a topologia efetiva do ambiente:

- o admin entra na tela inicial e depois acessa `Config` ja autenticado;
- PACS local ou externo;
- MWL local ou externa;
- URL publica do cockpit;
- status efetivo de banco, PACS e worklist;
- submenus separados para integracoes, valores, status e deploy, com apenas um painel visivel por vez;
- readiness de deploy no Render.

Use essa tela sempre que:

- o cockpit estiver publicado separado dos servicos DICOM;
- a URL publica do projeto mudar;
- for preciso alternar entre integracao local e externa.

## 2.14 Docs

Abre o portal `/docs/index.html` em nova aba.

Use para:

- consultar fluxogramas durante implantacao ou treinamento;
- revisar API, deploy e arquitetura;
- onboard de operadores tecnicos e equipe de suporte.

## 3. Fluxos operacionais principais

## 3.1 Cadastro ate publicacao em worklist

1. cadastrar paciente em `Pacientes`, se necessario;
2. cadastrar ou revisar procedimento em `Exames`;
3. criar o exame com agenda, modalidade e AET;
4. publicar na worklist;
5. confirmar em `Worklist` se a fila local ficou coerente.

## 3.2 Chegada do paciente e execucao

1. marcar chegada ou mover o exame no Kanban;
2. executar o exame e acompanhar a mudanca para `started` ou `executed`;
3. validar se o PACS encontrou o estudo depois da aquisicao;
4. abrir `Laudos & Viewer` para revisar midia.

## 3.3 Laudo e entrega

1. abrir workspace;
2. conferir anexos e previews;
3. salvar laudo;
4. gerar ou revisar compartilhamento;
5. encaminhar para finalizacao.

## 3.4 Fluxo de chamada no painel

1. garantir que o exame gerou senha/fila;
2. escolher o destino na tela `Painel`;
3. disparar a chamada;
4. acompanhar historico e fila;
5. usar tela cheia quando o painel estiver em exibicao publica.

## 3.5 Fluxo de suporte tecnico

1. revisar `Dashboard` para sintomas gerais;
2. usar `Config` para ver status efetivo de banco, PACS e MWL;
3. usar `Storage` para conferir disco e backups;
4. consultar `Docs` para troubleshooting e fluxogramas.

## 4. Rotina recomendada por perfil

## 4.1 Recepcao

- revisar Dashboard no inicio do turno;
- cadastrar paciente e exame;
- publicar worklist;
- operar painel de chamadas quando aplicavel.

## 4.2 Tecnico de imagem

- acompanhar Kanban e Worklist;
- confirmar modalidade, AET e fila;
- validar o painel e o fluxo de chamadas quando houver apoio operacional.

## 4.3 Radiologista

- usar `Laudos & Viewer`;
- revisar DICOM/anexos;
- concluir laudos e liberar compartilhamentos.

## 4.4 Financeiro

- revisar `Financeiro`;
- marcar faturas como pagas;
- cruzar com status do exame quando necessario.

## 4.5 TI / implantacao

- operar `Config`, `Storage` e `Docs`;
- revisar DICOM/MWL, backups, deploy e logs externos do host;
- validar `PORT`, banco, runtime e `ffmpeg`.

## 5. Checklist diario

- Dashboard sem alertas criticos;
- banco, PACS e worklist respondendo;
- fila de exames coerente com agenda do dia;
- painel de chamadas funcionando;
- painel e filas de chamadas online;
- backup recente disponivel quando houver mudanca de ambiente.

## 6. Erros comuns de uso

### 6.1 Exame nao aparece na MWL

- revisar se foi publicado;
- conferir `Config` para ver se a worklist efetiva e local ou externa;
- checar etapa e status do exame.

### 6.2 Viewer sem conteudo

- confirmar se o estudo DICOM ja entrou no PACS;
- revisar se anexos foram enviados;
- abrir `Storage` para validar runtime/imagebox.

### 6.3 Compartilhamento nao abre

- confirmar URL publica em `Config`;
- conferir se o compartilhamento esta ativo;
- validar usuario e senha do slug.

### 6.4 Funcao de cameras removida

- a aba de cameras nao faz parte da interface atual;
- use o painel e o chat por departamentos para a operacao diaria.

## 7. Resumo

Se a equipe guardar apenas uma regra operacional, ela deve ser esta:

- `Pacientes` e `Exames` constroem a base;
- `Worklist` e `Kanban` governam a fila;
- `Laudos & Viewer` finalizam o produto medico;
- `Financeiro`, `Comunicacao`, `Painel` e `Storage` sustentam a operacao;
- `Config` define a topologia real;
- `Docs` explica tudo isso dentro da propria aplicacao.
