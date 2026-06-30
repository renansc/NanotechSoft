# Diagramas e Processos do Sistema RioBranco

## 1. Objetivo

Este documento agrupa diagramas Mermaid focados em processo, operacao e integracao.

Ele complementa:

- `ARQUITETURA_SISTEMA.md`
- `OPERACAO_E_DEPLOY.md`
- `API_E_DADOS.md`

## 2. Mapa macro do sistema

```mermaid
flowchart TB
    U[Usuarios] --> N[Nginx]
    N --> APP[Flask app]
    U --> WEBUI[Open WebUI]
    WEBUI --> OLLAMA[Ollama / Qwen]
    APP --> OLLAMA
    APP --> DB[(MariaDB)]
    APP --> FS[Arquivos e volumes]
    APP --> PBX[FreePBX]
    APP --> ESXI[Monitor ESXi]
    APP --> CAM[Monitor Cameras]
    APP --> AUTO[Monitor Automacao]
    PBX --> TRUNK[Tronco SIP]
```

## 3. Processo de deploy completo

```mermaid
flowchart TD
    A[Git pull ou checkout inicial] --> B[docker compose up -d --build]
    B --> C[db]
    C --> D[db-restore]
    D --> E{Banco vazio?}
    E -->|sim| F[Importa backup mais recente]
    E -->|nao| G[Pula restore]
    F --> H[cert-bootstrap]
    G --> H
    H --> I{RB_CERT_BOOTSTRAP=1?}
    I -->|sim| J[Gera CA e certificados]
    I -->|nao| K[Pula bootstrap de certificado]
    J --> L[Instala WSS no FreePBX]
    L --> M[Ollama sobe]
    K --> M
    M --> N[ollama-model-init garante Qwen]
    N --> O[Open WebUI sobe]
    N --> P[app sobe]
    P --> Q[ensure_schema]
    Q --> R[proxy sobe]
    O --> S[Sistema pronto]
    R --> S
```

## 4. Processo de inicializacao do backend

```mermaid
flowchart TD
    A[server.py inicia] --> B[carrega .env]
    B --> C[define diretorios de dados]
    C --> D[configura conexao MariaDB]
    D --> E[bootstrap de SIP por env]
    E --> F[ensure_schema]
    F --> G[rotas Flask ficam disponiveis]
    G --> H[monitores sobem sob demanda]
```

## 5. Fluxo de requisicao web

```mermaid
sequenceDiagram
    participant U as Navegador
    participant N as Nginx
    participant A as Flask
    participant DB as MariaDB
    participant FS as Disco

    U->>N: GET/POST
    N->>A: proxy_pass
    A->>DB: SELECT/INSERT/UPDATE
    A->>FS: leitura/escrita quando necessario
    A-->>N: resposta
    N-->>U: HTML/JSON/arquivo
```

## 6. Processo de login e sessao

```mermaid
flowchart TD
    A[usuario informa login e senha] --> B[POST /api/login]
    B --> C[backend consulta usuarios]
    C --> D{senha valida?}
    D -->|nao| E[retorna 401]
    D -->|sim| F{usuario ativo?}
    F -->|nao| G[retorna 403]
    F -->|sim| H[frontend salva sessao no localStorage]
    H --> I[frontend passa X-Usuario-* nas chamadas]
    I --> J[chat e SIP usam usuario autenticado]
```

## 7. Processo de criacao ou edicao de usuario

```mermaid
flowchart TD
    A[usuario admin cria/edita cadastro] --> B[POST ou PUT /api/usuarios]
    B --> C[backend valida nome e login]
    C --> D[grava senha hash do sistema]
    D --> E[define sip_usuario e sip_ramal]
    E --> F[define sip_senha]
    F --> G[_sincronizar_usuarios_sip]
    G --> H[_sincronizar_usuarios_freepbx]
    H --> I[ramal PJSIP criado/atualizado no FreePBX]
```

## 8. Processo de sincronizacao SIP no FreePBX

```mermaid
sequenceDiagram
    participant UI as Frontend/Admin
    participant API as Flask
    participant DB as MariaDB
    participant SSH as SSH Paramiko
    participant PBX as FreePBX

    UI->>API: POST /api/sip/freepbx/sync
    API->>DB: consulta usuarios SIP
    API->>API: monta payload final de ramais
    API->>SSH: conecta no FreePBX
    SSH->>PBX: executa script PHP/Core do FreePBX
    PBX-->>SSH: resultado por usuario
    SSH-->>API: statuses created/updated/converted/skipped
    API-->>UI: resumo consolidado
```

## 9. Processo de registro SIP do navegador

```mermaid
flowchart TD
    A[frontend abre chat/comunicacao] --> B[GET /api/sip/me]
    B --> C[recebe config global + credenciais do usuario]
    C --> D[instancia JsSIP]
    D --> E[abre WSS para o FreePBX]
    E --> F[envia REGISTER]
    F --> G{registro aceito?}
    G -->|sim| H[cliente web fica disponivel]
    G -->|nao| I[frontend mostra erro]
```

## 10. Chamada SIP interna

```mermaid
sequenceDiagram
    participant A as Usuario A
    participant JA as JsSIP A
    participant PBX as FreePBX
    participant JB as JsSIP B
    participant B as Usuario B

    A->>JA: clicar em ligar
    JA->>PBX: INVITE ramal interno
    PBX->>JB: toca no destino
    JB->>B: chamada recebida
    B->>JB: atender
    JB->>PBX: 200 OK
    PBX->>JA: 200 OK
    JA->>PBX: ACK
    Note over A,B: audio estabelecido
    A->>JA: encerrar
    JA->>PBX: BYE
    PBX->>JB: BYE
```

## 11. Chamada SIP externa

```mermaid
flowchart LR
    A[Usuario web] --> B[JsSIP]
    B --> C[FreePBX]
    C --> D{usuario com sip_habilitado?}
    D -->|nao| E[bloqueia discagem externa]
    D -->|sim| F[aplica rota de saida]
    F --> G[tronco SIP]
    G --> H[operadora]
    H --> I[numero externo]
```

## 12. Processo de backup SQL

```mermaid
flowchart TD
    A[usuario clica em gerar backup] --> B[GET /api/backup]
    B --> C[backend monta comando mariadb-dump]
    C --> D[gera arquivo temporario]
    D --> E[copia para backupsSql]
    E --> F[retorna arquivo para download]
    F --> G[remove arquivo temporario]
```

## 13. Processo de restore automatico

```mermaid
flowchart TD
    A[container db-restore inicia] --> B[aguarda banco ficar pronto]
    B --> C[procura backup mais recente]
    C --> D{ha backup?}
    D -->|nao| E[encerra sem restaurar]
    D -->|sim| F{banco vazio ou force?}
    F -->|nao| G[pula restauracao]
    F -->|sim| H[importa .sql ou .sql.gz]
    H --> I[encerra com sucesso]
```

## 14. Processo de devolucao com fotos

```mermaid
flowchart TD
    A[usuario preenche devolucao] --> B[envia formulario com arquivos]
    B --> C[backend grava devolucao]
    C --> D[gera devolucao_id]
    D --> E[salva fotos em FotosDevolucoes/devolucao_id]
    E --> F[atualiza campo fotos no banco]
    F --> G[listagem passa a expor URLs]
```

## 15. Processo de abastecimento

```mermaid
flowchart TD
    A[operador libera abastecimento] --> B[POST /api/abastecimentos/liberar]
    B --> C[registro nasce como liberado]
    C --> D[gera PDF da requisicao]
    D --> E[posto executa abastecimento]
    E --> F{preenchimento manual ou XML?}
    F -->|manual| G[PUT /api/abastecimentos/id/abastecer]
    F -->|XML NF-e| H[POST /api/abastecimentos/id/importar_nfe]
    G --> I[valor e litros sao gravados]
    H --> I
    I --> J[status muda para abastecido]
    J --> K[historicos de frota passam a considerar o evento]
```

## 16. Processo de chat interno

```mermaid
flowchart TD
    A[usuario escreve mensagem] --> B{ha anexo?}
    B -->|nao| C[POST /api/chat/mensagens JSON]
    B -->|sim| D[POST /api/chat/mensagens multipart]
    D --> E[backend salva anexo em disco]
    C --> F[backend grava chat_mensagens]
    E --> F
    F --> G[destinatario faz polling]
    G --> H[GET /api/chat/unread]
    H --> I[contador e atualizado]
    I --> J[ao abrir conversa, GET /api/chat/conversa]
    J --> K[download inline ou arquivo por /api/chat/mensagens/id/anexo]
    K --> L[PUT /api/chat/marcar_lidas]
```

## 17. Processo do monitor ESXi

```mermaid
flowchart LR
    A[usuario abre aba Monitor ESXi] --> B[/monitor/esxi]
    B --> C[backend verifica app auxiliar]
    C --> D{processo rodando?}
    D -->|nao| E[inicia app.py do modulo ESXi]
    D -->|sim| F[usa processo existente]
    E --> G[proxy para porta local do monitor]
    F --> G
    G --> H[usuario interage com ESXi/vCenter]
```

## 18. Processo do monitor de cameras

```mermaid
flowchart TD
    A[usuario abre monitor de cameras] --> B[/monitor/cameras]
    B --> C[backend garante server.py de cameras]
    C --> D[app de cameras consulta SQLite]
    D --> E[lista cameras]
    E --> F{camera RTSP?}
    F -->|sim| G[FFmpeg pode gerar HLS local]
    F -->|nao| H[usa HLS configurado]
    G --> I[stream entregue ao navegador]
    H --> I
```

## 19. Processo do monitor de automacao

```mermaid
flowchart TD
    A[usuario abre Monitor Automacao] --> B[/monitor/automacao]
    B --> C[backend garante app.py industrial]
    C --> D[app usa prefixo encaminhado pelo proxy]
    D --> E[consulta SQLite em app_data/automacao]
    F[sensor envia POST api/leitura] --> G[leitura e alarmes sao persistidos]
    G --> E
    E --> H[telas de motores, historico, alarmes e tempo real]
```

## 20. Processo de bootstrap de certificados

```mermaid
flowchart TD
    A[cert-bootstrap inicia] --> B[le variaveis RB_CERT_*]
    B --> C{RB_CERT_BOOTSTRAP=1?}
    C -->|nao| D[sai sem alterar certificados]
    C -->|sim| E[garante CA interna]
    E --> F[emite certificado do app]
    F --> G[emite certificado do FreePBX]
    G --> H[instala arquivos no PBX via SSH]
    H --> I[configura HTTPTLSCERTFILE e HTTPTLSPRIVATEKEY]
    I --> J[reinicia fwconsole]
    J --> K[aguarda TLS do WSS responder]
```

## 21. Processo de onboarding de certificados no cliente

```mermaid
flowchart TD
    A[cliente acessa sistema] --> B{ja confia na CA?}
    B -->|sim| C[segue para login e SIP]
    B -->|nao| D[baixa CA ou script de onboarding]
    D --> E[instala CA no trust store do dispositivo]
    E --> F[reabre navegador]
    F --> G[HTTPS e WSS passam a ser confiaveis]
```

## 22. Processo de diagnostico SIP

```mermaid
flowchart TD
    A[cliente SIP indisponivel] --> B[verificar /api/status]
    B --> C{endpoint SIP acessivel?}
    C -->|nao| D[problema de rede ou porta]
    C -->|sim| E[verificar confianca do certificado]
    E --> F{cliente confia na CA?}
    F -->|nao| G[instalar CA]
    F -->|sim| H[verificar /api/sip/me]
    H --> I{credenciais coerentes?}
    I -->|nao| J[sincronizar FreePBX]
    I -->|sim| K[inspecionar logs do Asterisk]
```

## 23. Processo de remocao de usuario

```mermaid
flowchart TD
    A[admin exclui usuario] --> B[DELETE /api/usuarios/id]
    B --> C[backend remove do MariaDB]
    C --> D[registra logs_exclusoes]
    D --> E{usuario tinha ramal?}
    E -->|nao| F[fim]
    E -->|sim| G[tenta remover extensao no FreePBX]
    G --> F
```

## 24. Processo de leitura recomendado

```mermaid
flowchart LR
    A[Arquitetura] --> B[Diagramas]
    B --> C[Operacao e Deploy]
    C --> D[API e Dados]
```

## 25. Processo de estoque com XML da NF-e

```mermaid
flowchart TD
    A[operador bipa chave ou escolhe XML] --> B[POST /api/estoque/nfe/import]
    B --> C[backend parseia XML oficial]
    C --> D{nota duplicada?}
    D -->|sim| E[retorna conflito]
    D -->|nao| F[gera ou atualiza conferencia]
    F --> G[auto cadastra produtos faltantes]
    G --> H[preenche itens da conferencia]
    H --> I[operador ajusta quantidades]
    I --> J[POST /api/estoque/conferencias/id/confirmar]
    J --> K[backend grava movimentos de estoque]
    K --> L[saldo e dashboard_estoque sao atualizados]
```

## 26. Processo de sincronizacao producao -> homologacao

```mermaid
flowchart TD
    A[operador executa sync-production-to-homolog.sh] --> B[valida RB_CERT_BOOTSTRAP=0]
    B --> C[opcional: git pull da branch configurada]
    C --> D[stop app e proxy da homologacao]
    D --> E[backup do banco local em sync-backups]
    E --> F[baixa dump da producao via /api/backup]
    F --> G[importa dump no banco da homologacao]
    G --> H{sync volumes?}
    H -->|app_data| I[copia /data/app remoto para o volume local]
    H -->|cameras_data| J[copia /data/cameras remoto para o volume local]
    I --> K[sube app e proxy]
    J --> K
    G --> K
    K --> L[homologacao alinhada com a producao]
```

## 27. Processo do portal `/docs`

```mermaid
flowchart TD
    A[usuario abre Docs no menu] --> B[frontend abre /docs/index.html]
    B --> C[Nginx preserva host e porta no redirect]
    C --> D[Flask serve docs/index.html]
    D --> E[usuario escolhe arquitetura, diagramas, operacao ou API]
    E --> F[viewer HTML carrega o Markdown versionado]
```

## 28. Observacoes finais

Os diagramas deste arquivo mostram o comportamento pretendido do sistema com base no codigo atual. Eles sao especialmente uteis para:

- onboarding tecnico
- troubleshooting
- planejamento de mudancas
- explicacao de fluxo para outras equipes

Quando houver mudanca relevante de arquitetura, SIP, persistencia ou deploy, este documento deve ser atualizado junto com os demais arquivos em `docs/`.
