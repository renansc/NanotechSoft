# Monitoramento Industrial

Aplicacao Flask para cadastro de motores, recebimento de leituras e
acompanhamento de alarmes de RPM, temperatura e vibracao.

## Executar com Docker

Requisitos:

- Docker
- Docker Compose

Inicie a aplicacao:

```bash
docker compose up --build -d
```

Acesse <http://localhost:5000>.

O banco SQLite fica armazenado no volume Docker `sensores_data`, portanto os
dados permanecem disponiveis quando o container e recriado.

Para acompanhar os logs:

```bash
docker compose logs -f app
```

Para encerrar:

```bash
docker compose down
```

Para encerrar e apagar tambem os dados persistidos:

```bash
docker compose down -v
```

## Simulador

Cadastre primeiro um motor na interface. Depois execute o simulador informando
o ID do motor, caso ele seja diferente de `1`:

```bash
MOTOR_ID=1 docker compose --profile simulador up -d
```

O intervalo entre leituras pode ser configurado em segundos:

```bash
SENSOR_INTERVAL=10 docker compose --profile simulador up -d
```

## Sensores / Drivers Kollmorgen

O menu `Sensores > Drivers` permite cadastrar drives Kollmorgen AKD/AKD2G por
IP usando Modbus TCP. A porta padrao e `502`, o `Unit ID` padrao e `1`, e a
aplicacao cria tags iniciais para status do drive, entradas/saidas digitais,
velocidade, temperatura, corrente, barramento DC e falhas.

Ao associar o driver a um motor, a leitura de `VL.FB` e `MODBUS.PSCALE` e
convertida para RPM e gravada no historico normal de leituras do motor. Tags
adicionais podem ser cadastradas pelo endereco Modbus, quantidade de
registradores, tipo de dado e escala.

## Configuracao

Variaveis aceitas pelo Docker Compose:

| Variavel | Padrao | Descricao |
| --- | --- | --- |
| `APP_PORT` | `5000` | Porta exposta no computador |
| `MOTOR_ID` | `1` | Motor usado pelo simulador |
| `SENSOR_INTERVAL` | `5` | Intervalo do simulador em segundos |
| `DRIVER_MONITOR_ENABLED` | `1` | Liga/desliga a coleta automatica dos drivers |
