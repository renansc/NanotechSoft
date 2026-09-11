from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
)

import json
import math
import os

from database import (
    get_connection,
    init_database
)

from driver_service import (
    criar_tags_padrao,
    ler_driver,
    salvar_leitura_motor,
    start_driver_monitor
)
from machine_catalog import MACHINES, machine_by_slug

app = Flask(__name__)


@app.route("/")
def dashboard():

    conn = get_connection()

    total_motores = conn.execute("""
        SELECT COUNT(*) total
        FROM motores
    """).fetchone()["total"]

    total_leituras = conn.execute("""
        SELECT COUNT(*) total
        FROM leituras
    """).fetchone()["total"]

    total_alarmes = conn.execute("""
        SELECT COUNT(*) total
        FROM alarmes
        WHERE reconhecido = 0
    """).fetchone()["total"]

    total_maquinas = conn.execute("""
        SELECT COUNT(*) total
        FROM maquinas
        WHERE ativo = 1
    """).fetchone()["total"]

    maquinas_em_alarme = conn.execute("""
        SELECT COUNT(*) total
        FROM maquinas
        WHERE ativo = 1
          AND ultimo_status = 'alarme'
    """).fetchone()["total"]

    conn.close()

    return render_template(
        "dashboard.html",
        total_motores=total_motores,
        total_leituras=total_leituras,
        total_alarmes=total_alarmes,
        total_maquinas=total_maquinas,
        maquinas_em_alarme=maquinas_em_alarme,
    )


@app.route("/maquinas")
def maquinas():
    conn = get_connection()
    dados = conn.execute("""
        SELECT
            m.*,
            COUNT(DISTINCT p.id) pontos_total,
            COUNT(DISTINCT l.id) leituras_total
        FROM maquinas m
        LEFT JOIN maquina_pontos p
            ON p.maquina_id = m.id AND p.ativo = 1
        LEFT JOIN maquina_leituras l
            ON l.maquina_id = m.id
        GROUP BY m.id
        ORDER BY m.nome
    """).fetchall()
    conn.close()

    catalogo = {item["slug"]: item for item in MACHINES}
    return render_template(
        "maquinas.html",
        maquinas=dados,
        catalogo=catalogo,
    )


@app.route("/maquinas/<slug>")
def detalhe_maquina(slug):
    conn = get_connection()
    maquina = conn.execute(
        "SELECT * FROM maquinas WHERE slug = ?",
        (slug,),
    ).fetchone()
    if not maquina:
        conn.close()
        return redirect("/maquinas")

    pontos = conn.execute("""
        SELECT *
        FROM maquina_pontos
        WHERE maquina_id = ? AND ativo = 1
        ORDER BY grupo, nome
    """, (maquina["id"],)).fetchall()
    ultima = conn.execute("""
        SELECT *
        FROM maquina_leituras
        WHERE maquina_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (maquina["id"],)).fetchone()
    conn.close()

    leitura = _preparar_leitura_maquina(ultima) if ultima else None
    return render_template(
        "maquina_detalhe.html",
        maquina=maquina,
        pontos=pontos,
        leitura=leitura,
        documento=machine_by_slug(slug),
    )


@app.route("/documentacao")
def documentacao():
    return render_template("documentacao.html", maquinas=MACHINES)


@app.route("/documentacao/<slug>")
def documento_maquina(slug):
    maquina = machine_by_slug(slug)
    if not maquina:
        return redirect("/documentacao")
    return render_template("documento_maquina.html", maquina=maquina)


@app.route("/api/maquinas")
def api_maquinas():
    conn = get_connection()
    rows = conn.execute("""
        SELECT *
        FROM maquinas
        WHERE ativo = 1
        ORDER BY nome
    """).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["pontos"] = [
            dict(point)
            for point in conn.execute("""
                SELECT slug, nome, grupo, tipo, unidade,
                       limite_min, limite_max, alarme_quando, origem
                FROM maquina_pontos
                WHERE maquina_id = ? AND ativo = 1
                ORDER BY grupo, nome
            """, (row["id"],)).fetchall()
        ]
        result.append(item)
    conn.close()
    return jsonify({"maquinas": result})


@app.route("/api/maquinas/<slug>/ultima")
def api_ultima_leitura_maquina(slug):
    conn = get_connection()
    maquina = conn.execute(
        "SELECT id FROM maquinas WHERE slug = ? AND ativo = 1",
        (slug,),
    ).fetchone()
    if not maquina:
        conn.close()
        return jsonify({"erro": "maquina nao encontrada"}), 404
    leitura = conn.execute("""
        SELECT * FROM maquina_leituras
        WHERE maquina_id = ?
        ORDER BY id DESC LIMIT 1
    """, (maquina["id"],)).fetchone()
    conn.close()
    return jsonify(_preparar_leitura_maquina(leitura) if leitura else {})


@app.route("/api/maquinas/<slug>/leituras", methods=["POST"])
def api_receber_leitura_maquina(slug):
    if request.content_length and request.content_length > 65536:
        return jsonify({"erro": "leitura excede 64 KB"}), 413

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"erro": "envie um objeto JSON"}), 400
    valores = payload.get("pontos", payload.get("valores", payload))
    if not isinstance(valores, dict):
        return jsonify({"erro": "pontos deve ser um objeto JSON"}), 400

    conn = get_connection()
    maquina = conn.execute(
        "SELECT * FROM maquinas WHERE slug = ? AND ativo = 1",
        (slug,),
    ).fetchone()
    if not maquina:
        conn.close()
        return jsonify({"erro": "maquina nao encontrada"}), 404

    pontos = conn.execute("""
        SELECT * FROM maquina_pontos
        WHERE maquina_id = ? AND ativo = 1
    """, (maquina["id"],)).fetchall()
    por_slug = {point["slug"]: point for point in pontos}
    normalizados = {}
    alarmes = []
    ignorados = []

    try:
        for chave, valor in valores.items():
            if chave not in por_slug:
                ignorados.append(chave)
                continue
            point = por_slug[chave]
            normalizado = _normalizar_valor_ponto(point, valor)
            normalizados[chave] = normalizado
            motivo = _avaliar_alarme_ponto(point, normalizado)
            if motivo:
                alarmes.append({
                    "ponto": chave,
                    "nome": point["nome"],
                    "motivo": motivo,
                    "valor": normalizado,
                })
    except (TypeError, ValueError) as exc:
        conn.close()
        return jsonify({"erro": str(exc)}), 400

    if not normalizados:
        conn.close()
        return jsonify({
            "erro": "nenhum ponto conhecido foi informado",
            "ignorados": ignorados,
        }), 400

    erro = str(payload.get("erro") or "")[:500]
    status = "erro" if erro else ("alarme" if alarmes else "online")
    conn.execute("""
        INSERT INTO maquina_leituras(
            maquina_id, dados_json, status, alarmes_json, erro
        ) VALUES (?,?,?,?,?)
    """, (
        maquina["id"],
        json.dumps(normalizados, ensure_ascii=False),
        status,
        json.dumps(alarmes, ensure_ascii=False),
        erro or None,
    ))
    conn.execute("""
        UPDATE maquinas
        SET ultimo_status = ?,
            ultimo_erro = ?,
            ultimo_contato = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (status, erro or None, maquina["id"]))
    conn.commit()
    conn.close()
    return jsonify({
        "status": status,
        "alarmes": alarmes,
        "ignorados": ignorados,
        "pontos": normalizados,
    }), 201



@app.route("/motor/editar/<int:id>")
def editar_motor(id):

    conn = get_connection()
    motor = conn.execute("""
        SELECT *
        FROM motores
        WHERE id = ?
    """,(id,)).fetchone()
    setores = conn.execute("""
        SELECT *
        FROM setores
        ORDER BY nome
    """).fetchall()
    conn.close()
    return render_template(
        "motor_editar.html",
        motor=motor,
        setores=setores
    )

@app.route(
    "/motor/salvar/<int:id>",
    methods=["POST"]
)
def salvar_motor(id):

    conn = get_connection()

    conn.execute("""
        UPDATE motores
        SET
            nome = ?,
            setor_id = ?,
            rpm_alerta = ?,
            temperatura_alerta = ?,
            vibracao_alerta = ?
        WHERE id = ?
    """,
    (
        request.form["nome"],
        request.form["setor_id"],
        request.form["rpm_alerta"],
        request.form["temperatura_alerta"],
        request.form["vibracao_alerta"],
        id
    ))

    conn.commit()
    conn.close()

    return redirect("/motores")

@app.route("/api/ultima")
def ultima():

    conn = get_connection()

    leitura = conn.execute("""
        SELECT
            l.*,
            m.nome motor
        FROM leituras l
        JOIN motores m
            ON m.id = l.motor_id
        ORDER BY l.id DESC
        LIMIT 1
    """).fetchone()

    conn.close()

    if not leitura:
        return jsonify({})

    return jsonify(dict(leitura))

@app.route("/motor/excluir/<int:id>")
def excluir_motor(id):

    conn = get_connection()

    conn.execute("""
        DELETE FROM motores
        WHERE id = ?
    """, (id,))

    conn.commit()
    conn.close()

    return redirect("/motores")

@app.route("/motores")
def motores():

    conn = get_connection()

    dados = conn.execute("""
        SELECT
            m.*,
            s.nome setor
        FROM motores m
        LEFT JOIN setores s
            ON s.id = m.setor_id
        ORDER BY m.nome
    """).fetchall()

    setores = conn.execute("""
        SELECT *
        FROM setores
        ORDER BY nome
    """).fetchall()

    conn.close()

    return render_template(
        "motores.html",
        motores=dados,
        setores=setores
    )


@app.route("/motor/novo", methods=["POST"])
def novo_motor():

    conn = get_connection()

    conn.execute("""
        INSERT INTO motores(
            nome,
            setor_id
        )
        VALUES (?,?)
    """,
    (
        request.form["nome"],
        request.form["setor_id"]
    ))

    conn.commit()
    conn.close()

    return redirect("/motores")


@app.route("/historico")
def historico():

    conn = get_connection()

    dados = conn.execute("""
        SELECT
    l.*,
    m.nome motor
FROM leituras l
JOIN motores m
    ON m.id = l.motor_id
    """).fetchall()

    conn.close()

    return render_template(
        "historico.html",
        dados=dados
    )


@app.route("/alarmes")
def alarmes():

    conn = get_connection()

    dados = conn.execute("""
        SELECT *
        FROM alarmes
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "alarmes.html",
        dados=dados
    )

@app.route("/setores")
def setores():

    conn = get_connection()

    dados = conn.execute("""
        SELECT *
        FROM setores
        ORDER BY nome
    """).fetchall()

    conn.close()

    return render_template(
        "setores.html",
        setores=dados
    )

@app.route("/setor/novo", methods=["POST"])
def novo_setor():

    conn = get_connection()

    conn.execute("""
        INSERT INTO setores(
            nome,
            descricao
        )
        VALUES (?,?)
    """,
    (
        request.form["nome"],
        request.form["descricao"]
    ))

    conn.commit()
    conn.close()

    return redirect("/setores")

@app.route("/tempo-real")
def tempo_real():
    conn = get_connection()

    drivers = conn.execute("""
        SELECT
            d.*,
            m.nome motor
        FROM drivers d
        LEFT JOIN motores m
            ON m.id = d.motor_id
        ORDER BY d.nome
    """).fetchall()

    conn.close()

    return render_template(
        "tempo_real.html",
        drivers=drivers
    )


@app.route("/api/tempo-real")
def api_tempo_real():
    conn = get_connection()

    leitura_motor = conn.execute("""
        SELECT
            l.*,
            m.nome motor,
            m.rpm_alerta,
            m.temperatura_alerta,
            m.vibracao_alerta
        FROM leituras l
        JOIN motores m
            ON m.id = l.motor_id
        ORDER BY l.id DESC
        LIMIT 1
    """).fetchone()

    drivers = conn.execute("""
        SELECT
            d.*,
            m.nome motor
        FROM drivers d
        LEFT JOIN motores m
            ON m.id = d.motor_id
        ORDER BY d.nome
    """).fetchall()

    dados_drivers = []

    for driver in drivers:
        ultima = conn.execute("""
            SELECT *
            FROM driver_leituras
            WHERE driver_id = ?
            ORDER BY id DESC
            LIMIT 1
        """,(driver["id"],)).fetchone()

        dados_drivers.append(
            _preparar_driver_tempo_real(driver, ultima)
        )

    conn.close()

    return jsonify({
        "motor": dict(leitura_motor) if leitura_motor else None,
        "drivers": dados_drivers
    })


@app.route("/sensores")
def sensores():
    return redirect("/sensores/drivers")


@app.route("/sensores/drivers")
def sensores_drivers():

    conn = get_connection()

    drivers = conn.execute("""
        SELECT
            d.*,
            m.nome motor
        FROM drivers d
        LEFT JOIN motores m
            ON m.id = d.motor_id
        ORDER BY d.nome
    """).fetchall()

    motores = conn.execute("""
        SELECT *
        FROM motores
        ORDER BY nome
    """).fetchall()

    conn.close()

    return render_template(
        "drivers.html",
        drivers=drivers,
        motores=motores
    )


@app.route("/sensores/drivers/novo", methods=["POST"])
def novo_driver():

    conn = get_connection()

    motor_id = request.form.get("motor_id") or None

    cursor = conn.execute("""
        INSERT INTO drivers(
            nome,
            fabricante,
            modelo,
            protocolo,
            ip,
            porta,
            unit_id,
            motor_id,
            intervalo_segundos,
            timeout_segundos,
            ativo
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """,
    (
        request.form["nome"],
        "Kollmorgen",
        request.form.get("modelo", "AKD/AKD2G"),
        "kollmorgen_akd_modbus_tcp",
        request.form["ip"],
        request.form.get("porta", 502),
        request.form.get("unit_id", 1),
        motor_id,
        request.form.get("intervalo_segundos", 5),
        request.form.get("timeout_segundos", 3),
        1 if request.form.get("ativo") else 0
    ))

    criar_tags_padrao(conn, cursor.lastrowid)

    conn.commit()
    conn.close()

    return redirect("/sensores/drivers")


@app.route("/sensores/drivers/<int:id>")
def detalhe_driver(id):

    conn = get_connection()

    driver = conn.execute("""
        SELECT
            d.*,
            m.nome motor
        FROM drivers d
        LEFT JOIN motores m
            ON m.id = d.motor_id
        WHERE d.id = ?
    """,(id,)).fetchone()

    if not driver:
        conn.close()
        return redirect("/sensores/drivers")

    motores = conn.execute("""
        SELECT *
        FROM motores
        ORDER BY nome
    """).fetchall()

    tags = conn.execute("""
        SELECT *
        FROM driver_tags
        WHERE driver_id = ?
        ORDER BY id
    """,(id,)).fetchall()

    leituras = conn.execute("""
        SELECT *
        FROM driver_leituras
        WHERE driver_id = ?
        ORDER BY id DESC
        LIMIT 20
    """,(id,)).fetchall()

    conn.close()

    leituras = [
        _preparar_leitura_driver(leitura)
        for leitura in leituras
    ]
    ultima = leituras[0] if leituras else None

    return render_template(
        "driver_detalhe.html",
        driver=driver,
        motores=motores,
        tags=tags,
        leituras=leituras,
        ultima=ultima,
        tipos_tag=_tipos_tag()
    )


@app.route("/sensores/drivers/<int:id>/salvar", methods=["POST"])
def salvar_driver(id):

    conn = get_connection()

    motor_id = request.form.get("motor_id") or None

    conn.execute("""
        UPDATE drivers
        SET
            nome = ?,
            modelo = ?,
            ip = ?,
            porta = ?,
            unit_id = ?,
            motor_id = ?,
            intervalo_segundos = ?,
            timeout_segundos = ?,
            ativo = ?
        WHERE id = ?
    """,
    (
        request.form["nome"],
        request.form.get("modelo", "AKD/AKD2G"),
        request.form["ip"],
        request.form.get("porta", 502),
        request.form.get("unit_id", 1),
        motor_id,
        request.form.get("intervalo_segundos", 5),
        request.form.get("timeout_segundos", 3),
        1 if request.form.get("ativo") else 0,
        id
    ))

    conn.commit()
    conn.close()

    return redirect(f"/sensores/drivers/{id}")


@app.route("/sensores/drivers/<int:id>/excluir")
def excluir_driver(id):

    conn = get_connection()

    conn.execute("""
        DELETE FROM drivers
        WHERE id = ?
    """,(id,))

    conn.commit()
    conn.close()

    return redirect("/sensores/drivers")


@app.route(
    "/sensores/drivers/<int:id>/ler-agora",
    methods=["POST"]
)
def ler_driver_agora(id):

    ler_driver(id, ignorar_inativo=True)

    return redirect(f"/sensores/drivers/{id}")


@app.route(
    "/sensores/drivers/<int:id>/tags/novo",
    methods=["POST"]
)
def nova_tag_driver(id):

    conn = get_connection()

    conn.execute("""
        INSERT INTO driver_tags(
            driver_id,
            nome,
            endereco,
            registradores,
            tipo,
            escala,
            unidade,
            ativo
        )
        VALUES (?,?,?,?,?,?,?,?)
    """,
    (
        id,
        request.form["nome"],
        request.form["endereco"],
        request.form.get("registradores", 2),
        request.form.get("tipo", "int32"),
        request.form.get("escala", 1),
        request.form.get("unidade"),
        1 if request.form.get("ativo") else 0
    ))

    conn.commit()
    conn.close()

    return redirect(f"/sensores/drivers/{id}")


@app.route("/sensores/drivers/tags/<int:tag_id>/excluir")
def excluir_tag_driver(tag_id):

    conn = get_connection()

    tag = conn.execute("""
        SELECT *
        FROM driver_tags
        WHERE id = ?
    """,(tag_id,)).fetchone()

    if tag:
        conn.execute("""
            DELETE FROM driver_tags
            WHERE id = ?
        """,(tag_id,))
        conn.commit()
        driver_id = tag["driver_id"]
    else:
        driver_id = None

    conn.close()

    if driver_id:
        return redirect(f"/sensores/drivers/{driver_id}")

    return redirect("/sensores/drivers")


@app.route("/api/sensores/drivers/<int:id>/ultima")
def api_ultima_leitura_driver(id):

    conn = get_connection()

    leitura = conn.execute("""
        SELECT *
        FROM driver_leituras
        WHERE driver_id = ?
        ORDER BY id DESC
        LIMIT 1
    """,(id,)).fetchone()

    conn.close()

    if not leitura:
        return jsonify({})

    return jsonify(_preparar_leitura_driver(leitura))


@app.route(
    "/api/sensores/drivers/<int:id>/ler",
    methods=["POST"]
)
def api_ler_driver(id):
    return jsonify(
        ler_driver(id, ignorar_inativo=True)
    )


@app.route("/api/leitura", methods=["POST"])
def receber_leitura():

    payload = request.json

    conn = get_connection()

    salvar_leitura_motor(
        conn,
        payload["motor_id"],
        payload.get("rpm"),
        payload.get("temperatura"),
        payload.get("vibracao")
    )

    conn.commit()

    conn.close()

    return jsonify({
        "status": "ok"
    })


def _preparar_leitura_driver(leitura):
    item = dict(leitura)
    item["dados"] = json.loads(item["dados_json"] or "{}")
    item["raw"] = json.loads(item["raw_json"] or "{}")

    return item


def _preparar_leitura_maquina(leitura):
    item = dict(leitura)
    item["dados"] = json.loads(item.get("dados_json") or "{}")
    item["alarmes"] = json.loads(item.get("alarmes_json") or "[]")
    return item


def _normalizar_valor_ponto(point, value):
    tipo = point["tipo"]
    if tipo == "booleano":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "sim", "on", "ligado"}:
                return True
            if text in {"0", "false", "nao", "não", "off", "desligado"}:
                return False
        raise ValueError(f"{point['slug']} deve ser booleano")

    if tipo in {"numero", "contador"}:
        if isinstance(value, bool):
            raise ValueError(f"{point['slug']} deve ser numerico")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{point['slug']} deve ser um numero finito")
        if tipo == "contador":
            if number < 0 or not number.is_integer():
                raise ValueError(f"{point['slug']} deve ser inteiro e positivo")
            return int(number)
        return number

    if value is None:
        raise ValueError(f"{point['slug']} nao pode ser nulo")
    return str(value)[:200]


def _avaliar_alarme_ponto(point, value):
    if point["tipo"] == "booleano" and point["alarme_quando"] is not None:
        if bool(value) == bool(point["alarme_quando"]):
            return "estado de alarme ativo"
        return None

    if point["tipo"] not in {"numero", "contador"}:
        return None
    if point["limite_min"] is not None and value < point["limite_min"]:
        return f"abaixo do limite {point['limite_min']}"
    if point["limite_max"] is not None and value > point["limite_max"]:
        return f"acima do limite {point['limite_max']}"
    return None


def _preparar_driver_tempo_real(driver, ultima):
    return {
        "id": driver["id"],
        "nome": driver["nome"],
        "fabricante": driver["fabricante"],
        "modelo": driver["modelo"],
        "ip": driver["ip"],
        "porta": driver["porta"],
        "motor": driver["motor"],
        "ativo": bool(driver["ativo"]),
        "ultimo_status": driver["ultimo_status"],
        "ultimo_erro": driver["ultimo_erro"],
        "ultimo_contato": driver["ultimo_contato"],
        "ultimo_poll": driver["ultimo_poll"],
        "ultima": _preparar_leitura_driver(ultima) if ultima else None,
    }


def _tipos_tag():
    return [
        "uint16",
        "int16",
        "uint32",
        "int32",
        "uint64",
        "int64",
        "float32",
        "raw"
    ]

if __name__ == "__main__":

    init_database()
    start_driver_monitor()

    app.run(
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", os.getenv("PORT", "5000"))),
        debug=os.getenv("NS_DEBUG", "0").strip().lower() in {"1", "true", "yes", "sim", "on"},
        use_reloader=False
    )
