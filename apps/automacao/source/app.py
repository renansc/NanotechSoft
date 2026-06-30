from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect
)

import json
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

    conn.close()

    return render_template(
        "dashboard.html",
        total_motores=total_motores,
        total_leituras=total_leituras,
        total_alarmes=total_alarmes
    )



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
