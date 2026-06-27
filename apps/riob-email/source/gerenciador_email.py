#!/usr/bin/env python3
import threading
import time
from flask import jsonify
import os
import re
import sqlite3
import poplib
import email
from email.header import decode_header
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash

APP_DIR = os.path.abspath(os.path.dirname(__file__))
DB = os.path.join(APP_DIR, "emails.db")
ATTACH_DIR = os.path.join(APP_DIR, "anexos")

app = Flask(__name__)
app.secret_key = "riob1951@"
IMPORT_STATUS = {
    "running": False,
    "total": 0,
    "processed": 0,
    "imported": 0,
    "attachments": 0,
    "message": "Aguardando importação..."
}


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    os.makedirs(ATTACH_DIR, exist_ok=True)

    with db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            pop_host TEXT,
            pop_port INTEGER DEFAULT 995,
            use_ssl INTEGER DEFAULT 1,
            email_user TEXT,
            email_pass TEXT,
            storage_limit_gb REAL DEFAULT 5,
            delete_from_server INTEGER DEFAULT 0
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT UNIQUE,
            sender_name TEXT,
            sender_email TEXT,
            subject TEXT,
            email_date TEXT,
            imported_at TEXT
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER,
            filename TEXT,
            path TEXT,
            size_bytes INTEGER,
            created_at TEXT,
            FOREIGN KEY(email_id) REFERENCES emails(id)
        )
        """)

        con.execute("""
        INSERT OR IGNORE INTO config 
        (id, pop_host, pop_port, use_ssl, email_user, email_pass, storage_limit_gb)
        VALUES (1, '', 995, 1, '', '', 5)
        """)


def decode_text(value):
    if not value:
        return ""

    result = ""

    for text, enc in decode_header(value):
        if isinstance(text, bytes):
            result += text.decode(enc or "utf-8", errors="ignore")
        else:
            result += text

    return result.strip()


def sanitize(value):
    value = decode_text(str(value))
    value = re.sub(r'[\\/*?:"<>|]', "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:120] if value else "sem_nome"


def get_sender(msg):
    raw = msg.get("From", "")
    name, addr = email.utils.parseaddr(raw)

    sender_name = sanitize(name or addr.split("@")[0] or "sem_nome")
    sender_email = sanitize(addr.lower() or "sem_email")

    return sender_name, sender_email


def folder_for_sender(sender_name, sender_email):
    folder = sanitize(f"{sender_name} - {sender_email}")
    path = os.path.join(ATTACH_DIR, folder)
    os.makedirs(path, exist_ok=True)
    return path


def storage_used_bytes():
    total = 0

    for root, _, files in os.walk(ATTACH_DIR):
        for f in files:
            p = os.path.join(root, f)
            if os.path.exists(p):
                total += os.path.getsize(p)

    return total


def enforce_storage_limit(limit_gb):
    limit_bytes = int(float(limit_gb) * 1024 * 1024 * 1024)

    with db() as con:
        while storage_used_bytes() > limit_bytes:
            old = con.execute("""
                SELECT * FROM attachments
                ORDER BY created_at ASC
                LIMIT 1
            """).fetchone()

            if not old:
                break

            if os.path.exists(old["path"]):
                try:
                    os.remove(old["path"])
                except:
                    pass

            con.execute("DELETE FROM attachments WHERE id = ?", (old["id"],))


def connect_pop3(cfg):
    if cfg["use_ssl"]:
        server = poplib.POP3_SSL(
            cfg["pop_host"],
            int(cfg["pop_port"]),
            timeout=60
        )
    else:
        server = poplib.POP3(
            cfg["pop_host"],
            int(cfg["pop_port"]),
            timeout=60
        )

    server.user(cfg["email_user"])
    server.pass_(cfg["email_pass"])

    return server


def get_uid(server, index):
    """
    Correção do erro:
    ValueError: too many values to unpack

    Alguns servidores POP3/Python retornam formatos diferentes no uidl().
    Esta função trata todos.
    """

    result = server.uidl(index)

    if isinstance(result, tuple):
        uid_data = result[1]
    else:
        uid_data = result

    if isinstance(uid_data, list):
        uid_data = uid_data[0]

    if isinstance(uid_data, bytes):
        uid_text = uid_data.decode(errors="ignore")
    else:
        uid_text = str(uid_data)

    return uid_text.split()[-1]


def import_emails(max_emails=50):
    with db() as con:
        cfg = con.execute("SELECT * FROM config WHERE id = 1").fetchone()

    if not cfg["pop_host"] or not cfg["email_user"] or not cfg["email_pass"]:
        return 0, "Configure o POP3 primeiro."

    imported = 0
    server = connect_pop3(cfg)

    try:
        count, _ = server.stat()
        start = max(1, count - int(max_emails) + 1)
        IMPORT_STATUS["total"] = count - start + 1
        IMPORT_STATUS["processed"] = 0
        IMPORT_STATUS["imported"] = 0
        IMPORT_STATUS["attachments"] = 0
        IMPORT_STATUS["message"] = "Importando e-mails..."

        for i in range(start, count + 1):
            IMPORT_STATUS["processed"] += 1
            uid = get_uid(server, i)

            with db() as con:
                exists = con.execute(
                    "SELECT id FROM emails WHERE uid = ?",
                    (uid,)
                ).fetchone()

            if exists:
                continue

            retr_result = server.retr(i)

            if isinstance(retr_result, tuple):
                lines = retr_result[1]
            else:
                continue

            raw_msg = b"\n".join(lines)
            msg = email.message_from_bytes(raw_msg)

            sender_name, sender_email = get_sender(msg)
            subject = decode_text(msg.get("Subject", "Sem assunto"))
            email_date = decode_text(msg.get("Date", ""))

            with db() as con:
                cur = con.execute("""
                    INSERT INTO emails 
                    (uid, sender_name, sender_email, subject, email_date, imported_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    uid,
                    sender_name,
                    sender_email,
                    subject,
                    email_date,
                    datetime.now().isoformat(timespec="seconds")
                ))
                IMPORT_STATUS["attachments"] += 1

                email_id = cur.lastrowid

            sender_folder = folder_for_sender(sender_name, sender_email)

            for part in msg.walk():
                if part.get_content_disposition() != "attachment":
                    continue

                filename = part.get_filename()
                filename = sanitize(filename or "anexo")

                payload = part.get_payload(decode=True)

                if not payload:
                    continue

                final_name = f"{email_id}_{filename}"
                file_path = os.path.join(sender_folder, final_name)

                with open(file_path, "wb") as f:
                    f.write(payload)

                size = os.path.getsize(file_path)

                with db() as con:
                    con.execute("""
                        INSERT INTO attachments
                        (email_id, filename, path, size_bytes, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        email_id,
                        filename,
                        file_path,
                        size,
                        datetime.now().isoformat(timespec="seconds")
                    ))

            imported += 1
            IMPORT_STATUS["imported"] = imported
            if cfg["delete_from_server"]:
                server.dele(i)

        enforce_storage_limit(cfg["storage_limit_gb"])

    finally:
        server.quit()

    return imported, "Importação concluída."


BASE = """
<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<title>Gestão de E-mails e Anexos</title>
<style>
body {
    font-family: Arial;
    margin: 0;
    background: #f4f4f4;
}
header {
    background: #222;
    color: white;
    padding: 15px;
}
nav a {
    color: white;
    margin-right: 20px;
    text-decoration: none;
}
.container {
    padding: 20px;
}
.card {
    background: white;
    padding: 20px;
    border-radius: 8px;
    margin-bottom: 20px;
}
input {
    width: 100%;
    padding: 8px;
    margin: 6px 0 14px;
}
input[type=checkbox] {
    width: auto;
}
button {
    padding: 10px 18px;
    cursor: pointer;
}
table {
    width: 100%;
    border-collapse: collapse;
    background: white;
}
th, td {
    padding: 10px;
    border-bottom: 1px solid #ddd;
}
small {
    color: #666;
}
.alert {
    background: #e8ffe8;
    padding: 10px;
    margin-bottom: 15px;
}
</style>
</head>
<body>
<header>
<h2>Gestão de E-mails e Anexos</h2>
<nav>
<a href="/">Painel</a>
<a href="/config">Configuração POP3</a>
<a href="/emails">E-mails</a>
<a href="/anexos">Anexos</a>
<a href="/importaXml">ImportaXml</a>
</nav>
</header>

<div class="container">
{% with messages = get_flashed_messages() %}
{% if messages %}
{% for m in messages %}
<div class="alert">{{ m }}</div>
{% endfor %}
{% endif %}
{% endwith %}

{{ body|safe }}
</div>
</body>
</html>
"""


@app.route("/")
def index():
    used = storage_used_bytes()
    used_gb = used / 1024 / 1024 / 1024

    with db() as con:
        cfg = con.execute("SELECT * FROM config WHERE id = 1").fetchone()
        emails_total = con.execute("SELECT COUNT(*) total FROM emails").fetchone()["total"]
        anexos_total = con.execute("SELECT COUNT(*) total FROM attachments").fetchone()["total"]

    body = f"""
<div class="card">
    <h3>Resumo</h3>
    <p><b>E-mails importados:</b> {emails_total}</p>
    <p><b>Anexos salvos:</b> {anexos_total}</p>
    <p><b>Uso atual:</b> {used_gb:.2f} GB de {cfg['storage_limit_gb']} GB</p>

    <form method="post" action="/importar">
        <label>Quantidade máxima de e-mails para verificar</label>
        <input name="max_emails" type="number" value="50">
        <button>Importar agora</button>
    </form>
</div>

<div class="card">
    <h3>Status da importação</h3>

    <p id="status_text">Aguardando...</p>

    <div style="background:#ddd; border-radius:10px; overflow:hidden; height:26px;">
        <div id="progress_bar" style="
            width:0%;
            height:26px;
            background:#2d9b56;
            color:white;
            text-align:center;
            line-height:26px;
            transition:width 0.5s;">
            0%
        </div>
    </div>

    <p>
        <b>Verificados:</b> <span id="processed">0</span> /
        <span id="total">0</span>
    </p>

    <p><b>E-mails novos:</b> <span id="imported">0</span></p>
    <p><b>Anexos baixados:</b> <span id="attachments">0</span></p>
</div>

<script>
function atualizarStatus() {{
    fetch('/status_importacao')
        .then(r => r.json())
        .then(data => {{
            document.getElementById('status_text').innerText = data.message;
            document.getElementById('processed').innerText = data.processed;
            document.getElementById('total').innerText = data.total;
            document.getElementById('imported').innerText = data.imported;
            document.getElementById('attachments').innerText = data.attachments;

            let bar = document.getElementById('progress_bar');
            bar.style.width = data.percent + '%';
            bar.innerText = data.percent + '%';

            if (!data.running) {{
                clearInterval(statusTimer);
            }}
        }});
}}

let statusTimer = setInterval(atualizarStatus, 1000);
atualizarStatus();
</script>
"""

    return render_template_string(BASE, body=body)


@app.route("/config", methods=["GET", "POST"])
def config():
    if request.method == "POST":
        with db() as con:
            con.execute("""
                UPDATE config SET
                pop_host = ?,
                pop_port = ?,
                use_ssl = ?,
                email_user = ?,
                email_pass = ?,
                storage_limit_gb = ?,
                delete_from_server = ?
                WHERE id = 1
            """, (
                request.form["pop_host"],
                int(request.form["pop_port"]),
                1 if request.form.get("use_ssl") else 0,
                request.form["email_user"],
                request.form["email_pass"],
                float(request.form["storage_limit_gb"]),
                1 if request.form.get("delete_from_server") else 0
            ))

        flash("Configuração salva.")
        return redirect(url_for("config"))

    with db() as con:
        cfg = con.execute("SELECT * FROM config WHERE id = 1").fetchone()

    checked_ssl = "checked" if cfg["use_ssl"] else ""
    checked_del = "checked" if cfg["delete_from_server"] else ""

    body = f"""
    <div class="card">
        <h3>Configuração POP3</h3>

        <form method="post">
            <label>Servidor POP3</label>
            <input name="pop_host" value="{cfg['pop_host'] or ''}" placeholder="pop.gmail.com">

            <label>Porta</label>
            <input name="pop_port" type="number" value="{cfg['pop_port'] or 995}">

            <label>
                <input type="checkbox" name="use_ssl" {checked_ssl}>
                Usar SSL
            </label>

            <br><br>

            <label>E-mail</label>
            <input name="email_user" value="{cfg['email_user'] or ''}">

            <label>Senha / senha de app</label>
            <input name="email_pass" type="password" value="{cfg['email_pass'] or ''}">

            <label>Limite de armazenamento dos anexos em GB</label>
            <input name="storage_limit_gb" type="number" step="0.1" value="{cfg['storage_limit_gb']}">

            <label>
                <input type="checkbox" name="delete_from_server" {checked_del}>
                Apagar do servidor após importar
            </label>

            <br><br>
            <button>Salvar configuração</button>
        </form>
    </div>
    """

    return render_template_string(BASE, body=body)


@app.route("/importar", methods=["POST"])
def importar():
    if IMPORT_STATUS["running"]:
        flash("Já existe uma importação em andamento.")
        return redirect(url_for("index"))

    max_emails = int(request.form.get("max_emails", 50))

    def tarefa():
        IMPORT_STATUS["running"] = True
        IMPORT_STATUS["message"] = "Iniciando importação..."

        try:
            total, msg = import_emails(max_emails)
            IMPORT_STATUS["message"] = msg
        except Exception as e:
            IMPORT_STATUS["message"] = f"Erro: {e}"
        finally:
            IMPORT_STATUS["running"] = False

    threading.Thread(target=tarefa, daemon=True).start()

    return redirect(url_for("index"))

@app.route("/status_importacao")
def status_importacao():
    total = IMPORT_STATUS["total"]
    processed = IMPORT_STATUS["processed"]

    percent = 0
    if total > 0:
        percent = int((processed / total) * 100)

    return jsonify({
        "running": IMPORT_STATUS["running"],
        "total": total,
        "processed": processed,
        "imported": IMPORT_STATUS["imported"],
        "attachments": IMPORT_STATUS["attachments"],
        "message": IMPORT_STATUS["message"],
        "percent": percent
    })


@app.route("/emails")
def emails_page():
    with db() as con:
        rows = con.execute("""
            SELECT e.*, COUNT(a.id) total_anexos
            FROM emails e
            LEFT JOIN attachments a ON a.email_id = e.id
            GROUP BY e.id
            ORDER BY e.id DESC
        """).fetchall()

    html = """
    <div class="card">
        <h3>E-mails importados</h3>
        <table>
            <tr>
                <th>ID</th>
                <th>Remetente</th>
                <th>Assunto</th>
                <th>Data</th>
                <th>Anexos</th>
            </tr>
    """

    for r in rows:
        html += f"""
        <tr>
            <td>{r['id']}</td>
            <td>{r['sender_name']}<br><small>{r['sender_email']}</small></td>
            <td>{r['subject']}</td>
            <td>{r['email_date']}</td>
            <td>{r['total_anexos']}</td>
        </tr>
        """

    html += """
        </table>
    </div>
    """

    return render_template_string(BASE, body=html)


@app.route("/anexos")
def anexos_page():
    with db() as con:
        rows = con.execute("""
            SELECT a.*, e.sender_name, e.sender_email, e.subject
            FROM attachments a
            JOIN emails e ON e.id = a.email_id
            ORDER BY a.id DESC
        """).fetchall()

    html = """
    <div class="card">
        <h3>Anexos organizados</h3>
        <table>
            <tr>
                <th>Remetente</th>
                <th>Arquivo</th>
                <th>Tamanho</th>
                <th>Abrir</th>
            </tr>
    """

    for r in rows:
        size_mb = r["size_bytes"] / 1024 / 1024

        html += f"""
        <tr>
            <td>{r['sender_name']}<br><small>{r['sender_email']}</small></td>
            <td>{r['filename']}<br><small>{r['subject']}</small></td>
            <td>{size_mb:.2f} MB</td>
            <td><a href="/download/{r['id']}">Baixar</a></td>
        </tr>
        """

    html += """
        </table>
    </div>
    """

    return render_template_string(BASE, body=html)

@app.route("/importaXml")
def importaXml():
    return redirect("/apps/riob-xml/riob/")


@app.route("/download/<int:attachment_id>")
def download(attachment_id):
    with db() as con:
        row = con.execute(
            "SELECT * FROM attachments WHERE id = ?",
            (attachment_id,)
        ).fetchone()

    if not row or not os.path.exists(row["path"]):
        return "Arquivo não encontrado", 404

    return send_file(row["path"], as_attachment=True, download_name=row["filename"])


if __name__ == "__main__":
    init_db()
    app.run(
        host=os.environ.get("APP_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("APP_DEBUG", "0").strip().lower() in ("1", "true", "yes", "sim", "on"),
    )
