# API e Dados

## 1. Superficie HTTP principal

O backend Flask entrega dois tipos de recurso:

1. **paginas HTML e midias**;
2. **API JSON do cockpit**.

## 2. Paginas HTML e midias

| Metodo | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/` | Shell principal do cockpit |
| `GET` | `/login` | Tela de login por departamento |
| `POST` | `/login` | Confirma departamento e entra no cockpit |
| `GET` | `/logout` | Limpa a sessao do cockpit |
| `GET` | `/docs` e `/docs/` | Redireciona para o portal local de docs |
| `GET` | `/docs/<path:filename>` | Serve HTML, Markdown e assets do portal `/docs` |
| `GET` | `/viewer/exams/<exam_id>` | Viewer interno do exame |
| `GET` | `/share/<slug>` | Portal publico de compartilhamento |
| `POST` | `/share/<slug>/login` | Login do compartilhamento |
| `POST` | `/share/<slug>/logout` | Logout do compartilhamento |
| `GET` | `/media/exam-attachments/<attachment_id>` | Download ou visualizacao de anexos do exame |
| `GET` | `/media/pacs/objects/<sop_instance_uid>` | Download do objeto DICOM |
| `GET` | `/media/pacs/objects/<sop_instance_uid>/preview.png` | Preview PNG do objeto DICOM |
| `GET` | `/share/<slug>/media/exam-attachments/<attachment_id>` | Modo compartilhado para anexos liberados |
| `GET` | `/share/<slug>/media/pacs/objects/<sop_instance_uid>/preview.png` | Preview PNG sob sessao de compartilhamento |

## 3. Endpoints de health, admin, auth e integracao

| Metodo | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/api/ping` | Check minimo de disponibilidade |
| `GET` | `/api/health` | Health ampliado com banco, integracoes e settings |
| `POST` | `/api/admin/bootstrap` | Reexecuta bootstrap de schema |
| `POST` | `/api/auth/department` | Atualiza o departamento ativo da sessao |
| `GET` | `/api/integrations/config` | Le a configuracao PACS/MWL/Web |
| `PUT` | `/api/integrations/config` | Salva configuracao PACS/MWL/Web |
| `GET` | `/api/integrations/status` | Retorna status efetivo de banco, PACS e MWL |

Observacao: o acesso admin da interface vem do login inicial, entao a aba `Config` nao depende mais de um desbloqueio extra.

## 4. Endpoints de dashboard e operacao geral

| Metodo | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/api/overview` | Resume a operacao do cockpit |
| `GET` | `/api/kanban` | Dados para o quadro de fluxo |
| `POST` | `/api/exams/sync` | Sincroniza status de exames com o catalogo PACS/local |

## 4.1 Relatorios

| Metodo | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/api/reports/<report_type>` | Retorna o resumo JSON do relatorio |
| `GET` | `/reports/<report_type>.pdf` | Gera o PDF do relatorio para abrir em nova aba |

Os filtros aceitos sao:

- `period_mode=day|month`;
- `period_value=AAAA-MM-DD` para dia ou `AAAA-MM` para mes;
- `convenio_code` para restringir por convenio;
- `patient_id` para selecionar um paciente cadastrado.

O relatorio tambem alimenta os cards financeiros do dashboard com totais de pagos, em aberto e formas de pagamento.

## 5. Cadastros clinicos

### 5.1 Pacientes

| Metodo | Rota |
| --- | --- |
| `GET` | `/api/patients` |
| `POST` | `/api/patients` |
| `PUT` | `/api/patients/<patient_id>` |

### 5.2 Procedimentos

| Metodo | Rota |
| --- | --- |
| `GET` | `/api/procedures` |
| `POST` | `/api/procedures` |
| `PUT` | `/api/procedures/<procedure_id>` |

### 5.3 Operadores

| Metodo | Rota |
| --- | --- |
| `GET` | `/api/operators` |
| `POST` | `/api/operators` |
| `PUT` | `/api/operators/<operator_id>` |

## 6. Exames, laudos e viewer

| Metodo | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/api/exams` | Lista exames |
| `POST` | `/api/exams` | Cria exame |
| `PUT` | `/api/exams/<exam_id>` | Atualiza exame |
| `POST` | `/api/exams/<exam_id>/publish-worklist` | Publica/reespelha na worklist local |
| `POST` | `/api/exams/<exam_id>/remove-worklist` | Retira da worklist local |
| `GET` | `/api/exams/<exam_id>/workspace` | Workspace de laudo e viewer |
| `PUT` | `/api/exams/<exam_id>/report` | Salva laudo medico |
| `POST` | `/api/exams/<exam_id>/attachments` | Faz upload de anexo |
| `PUT` | `/api/exams/<exam_id>/workflow-stage` | Move etapa manual do exame |

## 7. Viewer e compartilhamento externo

| Metodo | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/api/viewer/exams/<exam_id>` | Dados do viewer interno |
| `POST` | `/api/viewer/shares` | Cria compartilhamento externo |
| `GET` | `/api/share/<slug>/workspace` | Workspace do compartilhamento autenticado |

## 8. Financeiro

| Metodo | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/api/finance/overview` | Totais financeiros |
| `GET` | `/api/finance/invoices` | Lista faturas |
| `POST` | `/api/finance/invoices/<invoice_id>/mark-paid` | Marca pagamento |

## 9. Comunicacao e SIP

| Metodo | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/api/chat/conversation` | Conversa entre operadores |
| `GET` | `/api/chat/departments` | Lista departamentos do chat com pendencias |
| `POST` | `/api/chat/messages` | Envia mensagem |
| `POST` | `/api/chat/read` | Marca conversa como lida |
| `GET` | `/api/chat/unread` | Totais nao lidos |

## 10. Painel

| Metodo | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/api/panel` | Lista fila/historico do painel |
| `POST` | `/api/panel/tickets/<ticket_id>/call` | Dispara chamada |
| `POST` | `/api/panel/tickets/<ticket_id>/status` | Altera status da senha |
| `GET` | `/api/panel/config` | Le configuracao do painel |
| `PUT` | `/api/panel/config` | Atualiza configuracao do painel |

## 11. Storage, backups e PACS web

| Metodo | Rota | Finalidade |
| --- | --- | --- |
| `GET` | `/api/storage` | Resumo de uso de disco e contadores PACS |
| `GET` | `/api/backups` | Lista backups |
| `POST` | `/api/backups/database` | Gera backup do banco |
| `POST` | `/api/backups/images` | Gera backup de imagens/anexos |
| `GET` | `/api/backups/<kind>/<filename>` | Download do backup |
| `GET` | `/api/pacs/studies` | Lista estudos PACS |
| `GET` | `/api/pacs/studies/<study_instance_uid>` | Detalhe do estudo PACS |

## 12. Servicos DICOM e MWL

## 12.1 PACS DICOM

`raiox_pacs/dicom_server.py` sobe uma `AE` com:

- `Verification`
- todos os `Storage Presentation Contexts`
- `StudyRootQueryRetrieveInformationModelFind`
- `StudyRootQueryRetrieveInformationModelGet`
- `StudyRootQueryRetrieveInformationModelMove`

Capacidades praticas:

- `C-ECHO` para ping;
- `C-STORE` para persistir instancias;
- `C-FIND` para buscar estudos/series/imagens catalogadas;
- `C-GET` e `C-MOVE` para recuperacao.

## 12.2 Modality Worklist

`raiox_pacs/worklist_server.py` expoe:

- `Verification`
- `ModalityWorklistInformationFind`

A MWL consulta `raiox.exam` + `raiox.patient` + `raiox.procedure_catalog` e monta datasets DICOM com:

- paciente;
- accession;
- `StudyInstanceUID`;
- modalidade;
- AET da estacao;
- data/hora agendada;
- prioridade e descricao do procedimento.

## 13. Modelo de dados

## 13.1 Schema clinico `raiox`

| Tabela | Papel |
| --- | --- |
| `raiox.patient` | Cadastro base do paciente |
| `raiox.procedure_catalog` | Catalogo de procedimentos |
| `raiox.exam` | Exame e seu fluxo operacional |
| `raiox.medical_report` | Laudo medico |
| `raiox.exam_attachment` | Anexos do exame |
| `raiox.share_access` | Compartilhamentos externos |
| `raiox.invoice` | Faturamento basico |
| `raiox.sync_log` | Log de eventos e sincronizacoes |
| `raiox.operator` | Operadores internos |
| `raiox.chat_message` | Mensagens entre operadores |
| `raiox.system_settings` | Configuracoes persistidas |
| `raiox.call_ticket` | Fila/senhas do painel |
| `raiox.call_log` | Historico de chamadas |

## 13.2 Tabelas PACS em `public`

| Tabela | Papel |
| --- | --- |
| `public.worklist` | Espelho/estrutura da worklist local |
| `public.study` | Catalogo de estudos DICOM |
| `public.series` | Catalogo de series DICOM |
| `public.reports` | Estrutura de status de laudo no legado PACS |
| `public.objects` | Objetos DICOM persistidos em disco |

## 14. Chaves de configuracao persistidas

Em `raiox.system_settings`, o bootstrap semeia pelo menos:

- `panel_config`
- `integration_config`

Essas chaves alimentam:

- tela `Config`;
- tela `Painel`;
- tela `Comunicacao`;
- calculo das URLs publicas e do status efetivo.

## 15. Campos importantes do exame

Os campos mais relevantes de `raiox.exam` para operar o fluxo sao:

- `accession_number`
- `study_instance_uid`
- `scheduled_at`
- `station_aet`
- `modality`
- `priority`
- `workflow_stage`
- `worklist_status`
- `pacs_study_found`
- `pacs_report_status`
- `price`
- `billing_status`

## 16. Observacoes de contrato

- a API responde JSON normalizado, com datas/decimais serializados;
- erros funcionais costumam voltar como `{"error": "..."}`;
- a aplicacao presume que o frontend principal fala com a mesma origem do Flask;
- o portal `/docs` tambem e servido pela mesma origem.

## 17. Resumo

Do ponto de vista de API e dados, o raioXPacs e organizado em torno de um eixo:

- **schema clinico `raiox.*`** para a operacao da clinica;
- **tabelas `public.*`** para o catalogo PACS/worklist;
- **rotas HTTP JSON** para o cockpit;
- **servicos DICOM e MWL** para integracao com modalidades e estações.
