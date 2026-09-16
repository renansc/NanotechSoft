# Automação e monitoramento industrial

Aplicação Flask integrada ao portal NanotechSoft para acompanhar máquinas,
motores, alarmes e drivers industriais. O banco SQLite é persistente e fica
fora do Git; o schema e o catálogo inicial das máquinas ficam versionados.

Use somente os comandos operacionais da raiz do repositório para testar ou
publicar o conjunto:

```bash
./up.sh
./down.sh
./update.sh
./git-safe-push.sh -m "mensagem"
```

## Máquinas documentadas

O catálogo inicial do Rio Branco contém:

- **Empacotadora Rodighero ER-1500**, série 104, fabricada em março/2024,
  capacidade nominal de 1.500 pacotes/h, alimentação 220 V, 59 kVA e sistema
  pneumático de 80 l/min a 6 bar.
- **Brix Zegla Unimix 20.000 L RZ-UC-20**, projeto elétrico 2000155283,
  alimentação 220 VCA, comando 24 VCC, 21 kW e corrente nominal de 72,6 A.
- **Impressora a laser Cyklop**, com protocolo de comunicacao N8 V1.2.
  Modelo fisico, serie e setor ainda nao informados. Possui seis pontos de
  monitoramento preparados para receber leituras; a coleta TCP/RS232 depende
  de um gateway a implementar e configurar.

O catalogo de documentos tambem inclui a **Envasadora Zegla 40/50/10 GA**,
modelo **RZ-RET-G-40/50/10-GA-GII**, desenho **2000164575**. E um equipamento
separado da Brix. O manual foi recuperado de `ProjetoEnchedora` em 14/09/2026;
o nome da capa foi confirmado pela operacao. O PDF existente possui 14 paginas.
Esse documento nao cria telemetria nem modifica os registros das outras maquinas.

No Rio Branco, abra **DOCUMENTOS > Automacao > Manuais das maquinas**
(`/apps/automacao/documentacao`). Cada maquina oferece o guia e o PDF fornecido
(manual fotografado ou protocolo de comunicacao). As fontes consolidadas estão em:

- `docs/EMPACOTADORA_RODIGHERO_ER1500.md`;
- `docs/BRIX_ZEGLA_UNIMIX_20000L.md`;
- `static/documentos/manual-fotografado-rodighero-er1500.pdf`;
- `static/documentos/diagramas-fotografados-zegla-unimix-20000l.pdf`;
- `docs/ENVASADORA_ZEGLA_40_50_10_GA.md`;
- `static/documentos/envasadora-zegla-40-50-10-ga.pdf`;
- `docs/IMPRESSORA_LASER_CYKLOP.md`;
- `static/documentos/protocolo-comunicacao-laser-cyklop-n8-v1.2.pdf`.

Os PDFs da empacotadora e da Brix foram gerados das fotografias fornecidas pela
operação, com remoção dos metadados das imagens. O PDF da envasadora foi copiado
integralmente do arquivo existente, sem alteração. Eles auxiliam a consulta, mas não substituem o
manual físico, os diagramas originais, análise de risco ou procedimentos de
bloqueio.

## Monitoramento das máquinas

Cada equipamento possui pontos esperados, última leitura, histórico e status:

- `aguardando`: ainda sem telemetria;
- `online`: leitura válida sem limite violado;
- `alarme`: limite ou estado de falha ativo;
- `erro`: o gateway informou erro de aquisição.

Os pontos foram escolhidos a partir das fontes fornecidas. Para Rodighero e
Zegla, IP, mapa de registradores e protocolo de telemetria nao estao confirmados
nas fotos. Para Cyklop, o PDF documenta consultas TCP/RS232, mas nao informa os
parametros da instalacao. A integração deve usar uma interface oficial, gateway isolado ou
contatos auxiliares aprovados pela engenharia. O portal não oferece comandos
de escrita nas máquinas.

### API de inventário

```http
GET /api/maquinas
GET /api/maquinas/<slug>/ultima
```

### Envio do gateway

Empacotadora:

```http
POST /api/maquinas/empacotadora-rodighero-er1500/leituras
Content-Type: application/json

{
  "pontos": {
    "contador_pacotes": 12050,
    "producao_pacotes_h": 1420,
    "pressao_ar_bar": 5.8,
    "temperatura_solda_c": 165,
    "temperatura_tunel_c": 180,
    "emergencia_acionada": false,
    "alarme_maquina": false
  }
}
```

Brix:

```http
POST /api/maquinas/brix-zegla-unimix-20000l/leituras
Content-Type: application/json

{
  "pontos": {
    "nivel_baixo": false,
    "nivel_alto": true,
    "agitador_ligado": true,
    "bomba_desareadora_ligada": true,
    "falha_bomba_desareadora": false,
    "corrente_total_a": 61.4,
    "emergencia_acionada": false
  }
}
```

Nomes desconhecidos são ignorados e devolvidos no campo `ignorados`. Valores
inválidos retornam HTTP 400. O corpo é limitado a 64 KB.

## Motores e sensores existentes

O cadastro de motores continua recebendo RPM, temperatura e vibração pela rota
`POST /api/leitura`. Alarmes usam os limites definidos em cada motor.

O menu **Sensores > Drivers** cadastra drives Kollmorgen AKD/AKD2G por Modbus
TCP. A porta padrão é 502 e o Unit ID padrão é 1. Tags iniciais cobrem status,
entradas/saídas digitais, velocidade, temperatura, corrente, barramento DC e
falhas. Ao associar um driver a um motor, `VL.FB` e `MODBUS.PSCALE` são
convertidos em RPM e gravados no histórico normal.

## Configuração

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `APP_PORT` | `5000` | Porta do serviço isolado |
| `DATABASE_PATH` | `homologacao.db` no app | Caminho do SQLite persistente |
| `DRIVER_MONITOR_ENABLED` | `1` | Liga/desliga a coleta automática dos drivers |
| `MOTOR_ID` | `1` | Motor usado pelo simulador legado |
| `SENSOR_INTERVAL` | `5` | Intervalo do simulador em segundos |

Alterações de schema são idempotentes durante o startup. A inicialização
acrescenta fichas e pontos ausentes, preservando leituras e ajustes existentes.
As fichas iniciais do Rio Branco, incluindo Cyklop, sao semeadas somente quando `CLIENTE_DEPLOY_ID=rio-branco`
(ou `NANOTECH_DEPLOY_PROFILE=rio-branco` na ausencia do primeiro); nao cria
cadastro operacional dessa maquina em outros clientes. Os documentos continuam
disponiveis no catalogo tecnico compartilhado.

`MACHINES` define o inventario monitorado; `DOCUMENTED_MACHINES` inclui tambem
equipamentos com apenas documentacao. `documented_machine_by_slug` resolve os
guias sem reaproveitar o slug ou o PDF de outra maquina.

## Menu do cliente Rio Branco

O perfil `menu_profiles.rio-branco` mantem Dashboard e Maquinas em Dash, agrupa Motores, Drivers e Maquinas em Cadastro como Equipamentos e tipos, conserva Setores separado e move Tempo real para Monitor e Historico/Alarmes para Gestao. Sao os mesmos cadastros e rotas, com autorizacao do modulo preservada. O desenho completo consta em `docs/MENU_RIO_BRANCO_PDF.md` na raiz.

Em 14/09/2026 foram restaurados Documentos > Manuais das maquinas e Workflow >
Kanban Automacao, omitidos pelo perfil anterior. O catalogo explicita o recurso
existente `automacao:*`; nao cria concessoes nem login. Listagem, guias e PDFs
passam pela sessao e autorizacao do portal. Testes cobrem todas as fontes do
catalogo, links reescritos sob `/apps/automacao` e acesso permitido/negado.

A Cyklop reutiliza esse mesmo recurso `automacao:*` em **Config > Usuarios e
acessos**, declarado no manifest. Documento, PDF, monitoramento e APIs passam
pela autorizacao do servidor no portal, incluindo o POST de leituras. A descricao
do catalogo inclui a Cyklop; nao ha novo recurso nem concessao automatica.

## Cadastro de manuais e documentacao pelo sistema

**CADASTRO > Automacao > Manual-documentacao** abre
`/apps/automacao/documentacao/cadastrar`. Informe titulo, equipamento/modelo
opcional, tipo (manual, protocolo de comunicacao ou documentacao tecnica),
descricao opcional e um PDF de ate 20 MB, valido, com paginas e sem senha.
Depois de salvar, o sistema abre **DOCUMENTOS > Automacao > Manuais das maquinas**
(`/apps/automacao/documentacao`), junto das fichas existentes. Nenhum documento
original e substituido. Incluir um documento nao cria uma maquina monitorada.

Os PDFs enviados e os metadados ficam na tabela `documentos_maquinas` do SQLite
persistente do cliente, fora do Git. A criacao da tabela e idempotente no startup.
O Compose preserva o banco no bind mount de `apps`; atualizar a aplicacao nao
remove os uploads. A listagem consulta apenas metadados; o binario e servido em
`GET /documentacao/arquivos/<id>`, pelo proxy autenticado, sem cache compartilhado.

Config > Usuarios e acessos oferece **Consultar manuais e documentacao**
(`automacao:documentos`) e **Cadastrar manuais e documentacao**
(`automacao:documentos_cadastrar`). O primeiro permite listagem, guias e PDFs;
o segundo permite o formulario GET/POST e a consulta do catalogo como dependencia.
Administradores e quem ja possui `automacao:*` continuam com acesso integral.
Nenhuma concessao individual e criada; acesso apenas a documentos nao libera
cadastros de motores, comandos ou APIs de telemetria. As mesmas verificacoes no
servidor se aplicam aos aliases `/original`. O Render continua somente leitura.

O proxy devolve o redirecionamento 303 ao navegador depois do envio para evitar
reenviar o PDF ao atualizar a pagina. Testes com banco temporario cobrem envio,
validacao, consulta, preservacao no startup, permissoes, menus e multipart.
