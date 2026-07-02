# Snapshot 2026-03-17

Checkpoint local do `raioxPacs` antes da proxima etapa de evolucao do worklist/kanban e da avaliacao de aderencia ao fluxo dcm4chee.

## Estado funcional

- dashboard operacional com metricas, mensagens recentes, storage e chamadas;
- kanban do fluxo radiologico com colunas de recepcao, fila, worklist, aquisicao, laudo e entrega;
- cadastro de pacientes, procedimentos e exames;
- faturamento basico com criacao automatica de fatura por exame;
- publicacao de exames na `public.worklist`;
- chat interno entre operadores;
- softphone WebRTC/SIP com configuracao por operador e perfil global;
- painel de chamadas com senha, historico, destinos e video;
- cadastro e monitor de cameras RTSP/HLS;
- runtime local para converter RTSP em HLS via `ffmpeg`;
- stack Docker com app, PostgreSQL e servidor DICOM Worklist.

## Estado tecnico

- schema `raiox` expandido com `operator`, `chat_message`, `camera`, `system_settings`, `call_ticket` e `call_log`;
- configuracao global de SIP e painel persistida em `raiox.system_settings`;
- assets locais `jssip.min.js` e `hls.min.js` empacotados em `static/vendor`;
- tema visual migrado para a linguagem da Cardio Clin.

## Validacao realizada

- `python3 -m py_compile` nos arquivos Python do projeto;
- `docker compose --env-file .env.docker.example config`;
- smoke test Flask com:
  - `GET` das rotas principais;
  - criacao de paciente;
  - criacao de exame;
  - criacao de operadores;
  - envio de mensagem;
  - criacao de camera HLS;
  - publicacao de exame na worklist;
  - chamada de senha no painel;
  - consulta de contexto SIP;
  - quitacao de fatura;
  - limpeza dos dados de teste ao final.

## Observacoes

- ainda nao houve build completo do Docker nesta etapa, apenas validacao de compose;
- o fluxo do kanban ainda usa etapas proprias da aplicacao e nao espelha todos os estados de worklist/equipamento;
- a worklist continua integrada a partir da base/estrutura atual, nao como um modulo completo independente no padrao dcm4chee.
