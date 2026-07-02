# Diagramas e Processos da Laboratorio Santa Terezinha

## 1. Como usar este arquivo

Abra este documento em:

- `documentacao.html?doc=DIAGRAMAS_E_PROCESSOS.md` para ler como Markdown;
- `diagramas.html` para navegar com renderizacao visual Mermaid.

## 2. Macroarquitetura do sistema

```mermaid
flowchart LR
    Browser[Equipe no navegador] --> Flask[Cockpit Flask / Gunicorn da Laboratorio Santa Terezinha]
    Flask --> Service[ClinicService]
    Service --> DB[(PostgreSQL)]
    Service --> Runtime[(runtime/imagebox + cameras + backups)]
    Service --> Viewer[Viewer / Compartilhamento]
    Flask --> Docs[Portal local /docs]
    Modality[Modalidades DICOM] --> PACS[DICOM SCP raioXPacs]
    PACS --> Runtime
    PACS --> DB
    Equipment[Estacoes / Modalidades] --> MWL[MWL SCP RAIOXMWL]
    MWL --> DB
    Service --> PACS
    Service --> MWL
```

## 3. Fluxo do exame do cadastro ate a finalizacao

```mermaid
flowchart TD
    A[Cadastro do paciente] --> B[Criacao do exame]
    B --> C[Publicacao na worklist local]
    C --> D[Paciente chega]
    D --> E[Exame em execucao]
    E --> F[Aquisicao concluida]
    F --> G[Objetos DICOM entram no PACS]
    G --> H[Workspace de laudo]
    H --> I[Laudo salvo]
    I --> J[Compartilhamento / entrega]
    J --> K[Exame finalizado]

    B -. cancelamento .-> X[Cancelado]
    C -. retirada da fila .-> Y[Removido]
```

## 4. Publicacao e consumo da worklist

```mermaid
sequenceDiagram
    participant Cockpit as Cockpit web
    participant Service as ClinicService
    participant DB as PostgreSQL
    participant MWL as RAIOXMWL
    participant Mod as Modalidade

    Cockpit->>Service: publicar exame na worklist
    Service->>DB: atualiza raiox.exam / public.worklist
    MWL->>DB: consulta exames elegiveis
    Mod->>MWL: C-FIND MWL
    MWL-->>Mod: dataset com paciente, accession, SPS e AET
```

## 5. Entrada de um estudo DICOM no PACS

```mermaid
sequenceDiagram
    participant Mod as Modalidade
    participant PACS as RAIOXPACS
    participant Catalog as pacs_catalog.py
    participant Runtime as imagebox
    participant DB as PostgreSQL

    Mod->>PACS: C-STORE
    PACS->>Catalog: store_instance(dataset, file_meta)
    Catalog->>Runtime: grava arquivo DICOM
    Catalog->>DB: atualiza public.study
    Catalog->>DB: atualiza public.series
    Catalog->>DB: atualiza public.objects
    PACS-->>Mod: status success
```

## 6. Fluxo do workspace, laudo e compartilhamento

```mermaid
flowchart TD
    A[Operador abre workspace] --> B[Backend monta payload do exame]
    B --> C[Busca anexos]
    B --> D[Busca estudo/series/objetos]
    C --> E[Viewer mostra anexos]
    D --> F[Viewer mostra previews DICOM]
    E --> G[Medico salva laudo]
    F --> G
    G --> H[Criacao de share externo]
    H --> I[Paciente acessa /share/slug]
    I --> J[Login do compartilhamento]
    J --> K[Workspace compartilhado]
```

## 7. Fluxo do painel de chamadas

```mermaid
flowchart LR
    Exam[Exame com senha] --> Ticket[call_ticket]
    Ticket --> PanelAPI[API do painel]
    PanelAPI --> Queue[Lista de fila e historico]
    Queue --> Screen[Tela publica do painel]
    PanelAPI --> Audio[Anuncio por voz]
    Operator[Operador] --> PanelAPI
    Operator --> Destination[Destino selecionado]
```

## 8. Fluxo das cameras

```mermaid
flowchart TD
    A[Cadastro da camera] --> B{Modo}
    B -->|RTSP| C[ffmpeg gera HLS em runtime/cameras]
    B -->|HLS direto| D[Frontend consome URL pronta]
    C --> E[/camera-streams/.../live.m3u8]
    D --> F[Monitor de cameras]
    E --> F
    F --> G[Status: starting, streaming, ready, error ou disabled]
```

## 9. Fluxo de backup

```mermaid
flowchart TD
    A[Usuario abre Storage] --> B[Solicita backup]
    B --> C{Tipo}
    C -->|Banco| D[create_database_backup]
    C -->|Imagens| E[create_images_backup]
    D --> F[Arquivo compactado no runtime]
    E --> F
    F --> G[Listagem em /api/backups]
    G --> H[Download pelo cockpit]
```

## 10. Fluxo do portal `/docs`

```mermaid
flowchart LR
    A[Usuario clica em Docs no menu] --> B[Nova aba em /docs/index.html]
    B --> C[Flask serve docs/index.html]
    C --> D[Viewer HTML carrega Markdown local]
    D --> E[marked renderiza o texto]
    D --> F[mermaid renderiza os diagramas]
```

## 11. Diagrama de dependencias operacionais

```mermaid
flowchart TD
    PORT[PORT / APP_PORT] --> Web[Servico web]
    DATABASE[DATABASE_URL / PG*] --> DB[PostgreSQL]
    RUNTIME[RUNTIME_ROOT] --> Storage[Imagebox, cameras, backups]
    FFMPEG[ffmpeg] --> Cameras[Conversao RTSP->HLS]
    DB --> Web
    DB --> PACS[PACS DICOM]
    DB --> MWL[MWL DICOM]
    Storage --> Viewer[Viewer e downloads]
    Storage --> Backups[Backups operacionais]
```

## 12. Leitura recomendada depois dos diagramas

- [Arquitetura](ARQUITETURA_SISTEMA.md)
- [Uso e Fluxos](USO_E_FLUXOS_FUNCIONAIS.md)
- [Operacao e Deploy](OPERACAO_E_DEPLOY.md)
- [API e Dados](API_E_DADOS.md)
