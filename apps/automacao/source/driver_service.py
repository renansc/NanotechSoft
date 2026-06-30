import json
import os
import threading
import time

from database import get_connection
from kollmorgen import (
    DEFAULT_KOLLMORGEN_TAGS,
    KollmorgenModbusClient,
    ModbusError,
    decode_registers,
    decode_status_bits,
)


_monitor_started = False
_monitor_lock = threading.Lock()


def criar_tags_padrao(conn, driver_id):
    for tag in DEFAULT_KOLLMORGEN_TAGS:
        conn.execute(
            """
            INSERT INTO driver_tags(
                driver_id,
                nome,
                endereco,
                registradores,
                tipo,
                escala,
                unidade
            )
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                driver_id,
                tag["nome"],
                tag["endereco"],
                tag["registradores"],
                tag["tipo"],
                tag["escala"],
                tag["unidade"],
            ),
        )


def salvar_leitura_motor(
    conn,
    motor_id,
    rpm=None,
    temperatura=None,
    vibracao=None,
):
    conn.execute(
        """
        INSERT INTO leituras(
            motor_id,
            rpm,
            temperatura,
            vibracao
        )
        VALUES (?,?,?,?)
        """,
        (
            motor_id,
            rpm,
            temperatura,
            vibracao,
        ),
    )

    conn.execute(
        """
        UPDATE motores
        SET ultimo_contato = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (motor_id,),
    )

    motor = conn.execute(
        """
        SELECT *
        FROM motores
        WHERE id = ?
        """,
        (motor_id,),
    ).fetchone()

    if not motor:
        return

    _registrar_alarme(
        conn,
        motor,
        "RPM",
        rpm,
        motor["rpm_alerta"],
    )
    _registrar_alarme(
        conn,
        motor,
        "TEMPERATURA",
        temperatura,
        motor["temperatura_alerta"],
    )
    _registrar_alarme(
        conn,
        motor,
        "VIBRACAO",
        vibracao,
        motor["vibracao_alerta"],
    )


def ler_driver(driver_id, ignorar_inativo=False):
    conn = get_connection()

    try:
        driver = conn.execute(
            """
            SELECT *
            FROM drivers
            WHERE id = ?
            """,
            (driver_id,),
        ).fetchone()

        if not driver:
            raise ValueError("Driver nao encontrado")

        if not ignorar_inativo and not driver["ativo"]:
            return {
                "status": "inativo",
                "erro": None,
                "dados": {},
            }

        tags = conn.execute(
            """
            SELECT *
            FROM driver_tags
            WHERE driver_id = ?
                AND ativo = 1
            ORDER BY id
            """,
            (driver_id,),
        ).fetchall()

        dados = {}
        raw = {}
        erros = []

        if not tags:
            status = "sem_tags"
            erro = "Nenhuma tag ativa cadastrada"
        else:
            status, erro = _coletar_tags(driver, tags, dados, raw, erros)

        conn.execute(
            """
            INSERT INTO driver_leituras(
                driver_id,
                dados_json,
                raw_json,
                status,
                erro
            )
            VALUES (?,?,?,?,?)
            """,
            (
                driver_id,
                json.dumps(dados, ensure_ascii=False),
                json.dumps(raw, ensure_ascii=False),
                status,
                erro,
            ),
        )

        contato_sql = "CURRENT_TIMESTAMP" if status in ("online", "parcial") else "ultimo_contato"
        conn.execute(
            f"""
            UPDATE drivers
            SET
                ultimo_status = ?,
                ultimo_erro = ?,
                ultimo_poll = CURRENT_TIMESTAMP,
                ultimo_contato = {contato_sql}
            WHERE id = ?
            """,
            (
                status,
                erro,
                driver_id,
            ),
        )

        normalizada = normalizar_leitura_motor(dados)
        if driver["motor_id"] and any(
            normalizada.get(campo) is not None
            for campo in ("rpm", "temperatura", "vibracao")
        ):
            salvar_leitura_motor(
                conn,
                driver["motor_id"],
                normalizada.get("rpm"),
                normalizada.get("temperatura"),
                normalizada.get("vibracao"),
            )

        conn.commit()

        return {
            "status": status,
            "erro": erro,
            "dados": dados,
            "raw": raw,
            "normalizada": normalizada,
        }
    finally:
        conn.close()


def normalizar_leitura_motor(dados):
    valores = {}

    for nome, item in dados.items():
        if "valor" in item:
            valores[nome.upper()] = item["valor"]

    rpm = None
    if "VL.FB" in valores:
        pscale = valores.get("MODBUS.PSCALE", 20)

        try:
            rpm = round(
                float(valores["VL.FB"]) * 60 / (2 ** int(pscale)),
                2,
            )
        except (TypeError, ValueError, OverflowError):
            rpm = None

    temperatura = _primeiro_valor(
        valores,
        "MOTOR.TEMPC",
        "MOTOR.TEMP",
        "TEMPERATURA",
        "TEMPERATURA.C",
    )
    vibracao = _primeiro_valor(
        valores,
        "VIBRACAO",
        "VIBRACAO.MM_S",
        "VIBRATION",
    )

    return {
        "rpm": rpm,
        "temperatura": temperatura,
        "vibracao": vibracao,
    }


def start_driver_monitor():
    global _monitor_started

    if os.getenv("DRIVER_MONITOR_ENABLED", "1") == "0":
        return

    with _monitor_lock:
        if _monitor_started:
            return

        thread = threading.Thread(
            target=_monitor_loop,
            name="driver-monitor",
            daemon=True,
        )
        thread.start()
        _monitor_started = True


def _monitor_loop():
    while True:
        try:
            _poll_due_drivers()
        except Exception:
            pass

        time.sleep(1)


def _poll_due_drivers():
    conn = get_connection()

    try:
        drivers = conn.execute(
            """
            SELECT *
            FROM drivers
            WHERE ativo = 1
                AND (
                    ultimo_poll IS NULL
                    OR datetime(
                        ultimo_poll,
                        '+' || intervalo_segundos || ' seconds'
                    ) <= CURRENT_TIMESTAMP
                )
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()

    for driver in drivers:
        ler_driver(driver["id"])


def _coletar_tags(driver, tags, dados, raw, erros):
    try:
        with KollmorgenModbusClient(
            driver["ip"],
            driver["porta"],
            driver["unit_id"],
            driver["timeout_segundos"],
        ) as client:
            for tag in tags:
                _coletar_tag(client, tag, dados, raw, erros)
    except (OSError, ModbusError) as error:
        return "erro", str(error)

    if erros and _tem_valores(dados):
        return "parcial", "; ".join(erros)[:500]
    if erros:
        return "erro", "; ".join(erros)[:500]

    return "online", None


def _coletar_tag(client, tag, dados, raw, erros):
    nome = tag["nome"]

    try:
        registers = client.read_holding_registers(
            tag["endereco"],
            tag["registradores"],
        )
        valor = decode_registers(registers, tag["tipo"])

        if isinstance(valor, (int, float)):
            valor = valor * float(tag["escala"] or 1)

        bits = None
        if isinstance(valor, (int, float)):
            bits = decode_status_bits(nome, int(valor))

        dados[nome] = {
            "valor": valor,
            "unidade": tag["unidade"],
            "endereco": tag["endereco"],
            "tipo": tag["tipo"],
            "bits": bits,
        }
        raw[nome] = registers
    except (OSError, ModbusError, ValueError) as error:
        mensagem = f"{nome}: {error}"
        erros.append(mensagem)
        dados[nome] = {
            "erro": str(error),
            "endereco": tag["endereco"],
            "tipo": tag["tipo"],
        }


def _registrar_alarme(conn, motor, tipo, valor, limite):
    if valor is None or limite is None:
        return

    try:
        valor_float = float(valor)
        limite_float = float(limite)
    except (TypeError, ValueError):
        return

    if valor_float <= limite_float:
        return

    conn.execute(
        """
        INSERT INTO alarmes(
            motor_id,
            tipo,
            valor,
            limite
        )
        VALUES (?,?,?,?)
        """,
        (
            motor["id"],
            tipo,
            valor_float,
            limite_float,
        ),
    )


def _primeiro_valor(valores, *nomes):
    for nome in nomes:
        valor = valores.get(nome)
        if valor is not None:
            return valor

    return None


def _tem_valores(dados):
    return any("valor" in item for item in dados.values())
