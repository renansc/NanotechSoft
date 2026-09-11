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

Os guias navegáveis ficam em `/documentacao`. As fontes consolidadas estão em:

- `docs/EMPACOTADORA_RODIGHERO_ER1500.md`;
- `docs/BRIX_ZEGLA_UNIMIX_20000L.md`;
- `static/documentos/manual-fotografado-rodighero-er1500.pdf`;
- `static/documentos/diagramas-fotografados-zegla-unimix-20000l.pdf`.

Os PDFs foram gerados das fotografias fornecidas pela operação, com remoção
dos metadados das imagens. Eles auxiliam a consulta, mas não substituem o
manual físico, os diagramas originais, análise de risco ou procedimentos de
bloqueio.

## Monitoramento das máquinas

Cada equipamento possui pontos esperados, última leitura, histórico e status:

- `aguardando`: ainda sem telemetria;
- `online`: leitura válida sem limite violado;
- `alarme`: limite ou estado de falha ativo;
- `erro`: o gateway informou erro de aquisição.

Os pontos foram escolhidos a partir dos manuais. IP, mapa de registradores e
protocolo de telemetria não foram inferidos, pois não estão confirmados nas
fotos. A integração deve usar uma interface oficial, gateway isolado ou
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

Alterações de schema são idempotentes durante o startup. A inicialização cria
as duas fichas de máquina e somente acrescenta pontos ausentes, preservando
leituras e ajustes existentes.

## Menu do cliente Rio Branco

O perfil `menu_profiles.rio-branco` mantem Dashboard e Maquinas em Dash, agrupa Motores, Drivers e Maquinas em Cadastro como Equipamentos e tipos, conserva Setores separado e move Tempo real para Monitor e Historico/Alarmes para Gestao. Sao os mesmos cadastros e rotas, com autorizacao do modulo preservada. O desenho completo consta em `docs/MENU_RIO_BRANCO_PDF.md` na raiz.
