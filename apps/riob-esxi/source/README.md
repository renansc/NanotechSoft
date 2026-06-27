# vSphere Flask Client

Interface web em `Flask + HTML + JavaScript` para administrar `ESXi` e `vCenter` sem depender do cliente Windows antigo do vSphere.

## O que este projeto entrega

Esta primeira versão cobre as operações administrativas mais frequentes:

- conexão com `ESXi` ou `vCenter`
- inventário com `datacenters`, `clusters`, `hosts`, `VMs`, `datastores`, `networks`, `resource pools` e `folders`
- ações de energia da VM: ligar, desligar, resetar, suspender, shutdown guest e reboot guest
- `rename` de VM
- ajuste de `CPU` e `RAM` da VM
- snapshots: listar, criar, reverter e remover
- clone de VM
- ações básicas de host: entrar/sair de maintenance mode, reboot e shutdown
- API HTTP própria para integrar com outros sistemas internos

## O que ainda nao cobre

Paridade total com o `vSphere Client` exigiria muitos módulos adicionais. Esta base ainda nao implementa:

- console HTML5 da VM
- browser de datastore com upload/download
- gerenciamento detalhado de storage, networking e switch distribuido
- vMotion, DRS, HA, vSAN e cluster lifecycle
- templates, content library e customização de SO
- tasks/events, alarmes, permissões/RBAC e auditoria
- montagem de ISO, dispositivos USB, PCI passthrough e configuracoes avancadas

## Estrutura

```text
vsphere-flask-client/
├── app.py
├── requirements.txt
├── README.md
└── vsphere_portal/
    ├── __init__.py
    ├── routes.py
    ├── session_store.py
    ├── services/
    │   └── vsphere.py
    ├── static/
    │   ├── app.js
    │   └── styles.css
    └── templates/
        ├── base.html
        └── index.html
```

## Como executar

```powershell
cd "C:\Users\renan\OneDrive\Área de Trabalho\vsphere-flask-client"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

A interface fica em `http://127.0.0.1:5000`.

Para producao no Windows:

```powershell
waitress-serve --listen=0.0.0.0:5000 app:app
```

## Variaveis de ambiente

- `FLASK_SECRET_KEY`: chave de sessao do Flask
- `FLASK_RUN_HOST`: host do servidor
- `FLASK_RUN_PORT`: porta do servidor
- `FLASK_DEBUG=1`: habilita debug

## API principal

### Sessao

- `GET /api/session`
- `POST /api/session/connect`
- `POST /api/session/disconnect`

### Inventario

- `GET /api/inventory`
- `GET /api/vms`
- `GET /api/vms/<moid>`
- `GET /api/hosts`

### VM

- `POST /api/vms/<moid>/power`
- `POST /api/vms/<moid>/rename`
- `POST /api/vms/<moid>/hardware`
- `GET /api/vms/<moid>/snapshots`
- `POST /api/vms/<moid>/snapshots`
- `POST /api/vms/<moid>/snapshots/<snapshot_moid>/revert`
- `DELETE /api/vms/<moid>/snapshots/<snapshot_moid>`
- `POST /api/vms/<moid>/clone`

### Host

- `POST /api/hosts/<moid>/maintenance`
- `POST /api/hosts/<moid>/power`

## Observacoes operacionais

- As credenciais ficam em memoria no processo Flask para manter a conexao ativa da sessao web.
- Em producao, coloque este app atras de `HTTPS`, rede restrita e autenticacao adicional.
- O `pyVmomi` funciona tanto para `ESXi` standalone quanto para `vCenter`.
- Se o ambiente usa certificado self-signed, deixe `Validar SSL` desmarcado no formulario.

## Proximos modulos recomendados

1. RBAC interno e log de auditoria.
2. Console remoto da VM via `WebMKS`.
3. Datastore browser com upload/download.
4. Tarefas/eventos e fila de jobs assincros.
5. Acoes de rede e storage por host/cluster.

## Referencia tecnica

Esta implementacao foi pensada sobre as APIs oficiais ainda mantidas em 2026:

- `pyVmomi` / vSphere Web Services API
- `VCF Python SDK` / vSphere Automation APIs
