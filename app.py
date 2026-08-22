from functools import wraps
import base64
import concurrent.futures
import datetime as dt
from decimal import Decimal
import hashlib
import html as html_lib
import json
import os
from pathlib import Path
import re
import mimetypes
import smtplib
import ssl
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import tempfile
from io import BytesIO
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for
import mysql.connector
from mysql.connector import errorcode
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from apps.financeiro.pdf_import import (
    FinancePdfImportError,
    extract_bank_statement_pdf,
    extract_installment_pdf,
    extract_installment_pdf_page,
)
from apps.financeiro.pdf_report import FinancePdfReportError, build_finance_titles_pdf
from apps.financeiro.pix import PixPayloadError, build_static_pix_payload
from apps.tecnologia.monitor import (
    build_network_diagnosis,
    device_network_addresses,
    discover_computers,
    discover_printers,
    measure_internet_speed,
    normalize_device_payload,
    probe_device,
)


BASE_DIR = Path(__file__).resolve().parent
BACKUP_FORMAT = "nanotechsoft.portal.backup"
BACKUP_VERSION = 1
MAX_BACKUP_BYTES = int(os.environ.get("NS_BACKUP_MAX_BYTES", str(25 * 1024 * 1024)))
MAX_FINANCE_PDF_BYTES = 15 * 1024 * 1024
MAX_FINANCE_ATTACHMENT_BYTES = 15 * 1024 * 1024


def load_env_file(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and os.environ.get(key) in (None, ""):
            os.environ[key] = value


def resolve_env_file(value):
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def load_runtime_env():
    configured = os.environ.get("NANOTECH_ENV_FILE")
    if configured:
        load_env_file(resolve_env_file(configured))
        return

    for filename in (".env", ".env_local"):
        path = BASE_DIR / filename
        if path.exists():
            load_env_file(path)
            return


load_runtime_env()

APPS_DIR = BASE_DIR / "apps"
ALLOWED_APPS_FILE = BASE_DIR / "apps_liberados.txt"
CLIENT_CONTRACTS_FILE = Path(
    os.environ.get("CLIENTES_MODULOS_FILE")
    or os.environ.get("CLIENT_CONFIG_FILE")
    or str(BASE_DIR / "clientes-modulos.json")
)
if not CLIENT_CONTRACTS_FILE.is_absolute():
    CLIENT_CONTRACTS_FILE = BASE_DIR / CLIENT_CONTRACTS_FILE


def app_source_dir(app_key):
    return APPS_DIR / app_key / "source"


AUTOMACAO_DIR = Path(os.environ.get(
    "AUTOMACAO_APP_DIR",
    str(app_source_dir("automacao")),
))
FINANCEIRO_DIR = BASE_DIR / "apps" / "financeiro"
FINANCEIRO_STATIC_DIR = FINANCEIRO_DIR / "static"
FINANCEIRO_ATTACHMENTS_DIR = Path(os.environ.get(
    "FINANCEIRO_ATTACHMENTS_DIR",
    str(FINANCEIRO_DIR / "dados" / "anexos"),
))
NANOPONTO_DIR = Path(os.environ.get("NANOPONTO_APP_DIR", str(app_source_dir("nanoponto"))))
ZAP_DIR = Path(os.environ.get("ZAP_APP_DIR", str(app_source_dir("zap"))))
NANOSTORE_DIR = Path(os.environ.get("NANOSTORE_APP_DIR", str(app_source_dir("nanostore"))))
GPSMUSICAL_DIR = Path(os.environ.get("GPSMUSICAL_APP_DIR", str(app_source_dir("gpsmusical"))))
BPA_DIR = Path(os.environ.get("BPA_APP_DIR", str(app_source_dir("bpa"))))
TATOO_DIR = Path(os.environ.get("TATOO_APP_DIR", str(app_source_dir("tatoo"))))
TECNOLOGIA_DIR = Path(os.environ.get("TECNOLOGIA_APP_DIR", str(app_source_dir("tecnologia"))))
RAIOXPACS_DIR = Path(os.environ.get("RAIOXPACS_APP_DIR", str(app_source_dir("pacs"))))
NANOTECH_SHARED_DIR = Path(os.environ.get("NANOTECH_SHARED_DIR", str(APPS_DIR / "shared")))
FINANCEIRO_COLLECTIONS = (
    "contas",
    "categorias",
    "lancamentos",
    "imports",
    "reconciliations",
    "ignoredBankTransactions",
    "favorecidos",
    "titulos",
    "compras",
)
FINANCEIRO_VIEWS = {
    "dashboard",
    "lancamentos",
    "contas",
    "categorias",
    "cadastros",
    "importar",
    "conciliacao",
    "compras",
    "pagar",
    "receber",
    "config",
}
FINANCEIRO_ACTIVE_PAGES = {
    "dashboard": "dashboards",
    "categorias": "cadastros",
    "cadastros": "cadastros",
    "conciliacao": "workflow",
    "compras": "compras",
    "contas": "financeiro",
    "pagar": "financeiro",
    "receber": "financeiro",
    "lancamentos": "relatorios",
    "importar": "import_export",
    "config": "config",
}
AUTOMACAO_PORT = int(os.environ.get("AUTOMACAO_PORT", "8890"))
AUTOMACAO_BASE_URL = f"http://127.0.0.1:{AUTOMACAO_PORT}"
AUTOMACAO_STARTUP_WAIT = float(os.environ.get("AUTOMACAO_STARTUP_WAIT", "60"))
NANOPONTO_PORT = int(os.environ.get("NANOPONTO_PORT", "8891"))
NANOPONTO_BASE_URL = f"http://127.0.0.1:{NANOPONTO_PORT}"
ZAP_PORT = int(os.environ.get("ZAP_PORT", "8892"))
ZAP_BASE_URL = f"http://127.0.0.1:{ZAP_PORT}"
NANOSTORE_PORT = int(os.environ.get("NANOSTORE_PORT", "8893"))
NANOSTORE_BASE_URL = f"http://127.0.0.1:{NANOSTORE_PORT}"
RAIOXPACS_PORT = int(os.environ.get("RAIOXPACS_PORT", "8899"))
RAIOXPACS_BASE_URL = f"http://127.0.0.1:{RAIOXPACS_PORT}"
RAIOXPACS_STARTUP_WAIT = float(os.environ.get("RAIOXPACS_STARTUP_WAIT", "90"))


RIOB_PROXY_ONLY = str(os.environ.get("RIOB_PROXY_ONLY") or "").strip().lower() in {"1", "true", "yes", "sim", "on"}


def resolve_riob_base_url():
    configured = str(os.environ.get("RIOB_BASE_URL") or "").strip()
    render_runtime = str(os.environ.get("RENDER") or "").strip().lower() == "true"
    configured_host = urllib.parse.urlparse(configured).hostname if configured else ""
    if RIOB_PROXY_ONLY:
        internal_hosts = {"host.docker.internal", "riob-proxy", "127.0.0.1", "localhost", "::1"}
        if not configured or configured_host in internal_hosts:
            return ""
        return configured
    if render_runtime and (not configured or configured_host == "host.docker.internal"):
        port = int(os.environ.get("RIOB_APP_PORT", "8898"))
        return f"http://127.0.0.1:{port}"
    return configured or "https://host.docker.internal:8899"


RIOB_BASE_URL = resolve_riob_base_url().rstrip("/")
RIOB_SSL_VERIFY = str(os.environ.get("RIOB_SSL_VERIFY", "0")).strip().lower() in {"1", "true", "yes", "sim", "on"}
RIOB_ROUTE_DEFAULTS = {
    "riob": "/",
    "riob-cameras": "/monitor/cameras/",
    "riob-telefonia": "/#config:sip",
    "riob-chat-ia": "/#agentia",
    "riob-chat": "/#comunicacao",
    "riob-email": "/gestor-emails/",
    "riob-esxi": "/monitor/esxi/",
    "riob-xml": "/importar-xml/",
}
LOCAL_RIOB_APPS = {
    "riob": {
        "cwd": APPS_DIR / "riob" / "source",
        "script": "server.py",
        "port": int(os.environ.get("RIOB_APP_PORT", "8898")),
        "startup_wait": float(os.environ.get("RIOB_STARTUP_WAIT", "180")),
        "env": {
            "APP_HOST": "127.0.0.1",
            "APP_PORT": os.environ.get("RIOB_APP_PORT", "8898"),
            "APP_HTTPS": "0",
            "RB_DATA_DIR": str(APPS_DIR / "riob" / "source"),
            "DB_HOST": os.environ.get("NS_DB_HOST", "mysql"),
            "DB_PORT": os.environ.get("NS_DB_PORT", "3306"),
            "DB_USER": os.environ.get("NS_DB_USER", "root"),
            "DB_PASSWORD": os.environ.get("NS_DB_PASSWORD", ""),
            "DB_NAME": os.environ.get("RIOB_DB_NAME", "riobranco"),
        },
    },
    "riob-cameras": {
        "cwd": APPS_DIR / "riob-cameras" / "source",
        "script": "server.py",
        "port": int(os.environ.get("RIOB_CAMERAS_PORT", "8894")),
        "env": {
            "APP_HOST": "127.0.0.1",
            "PORT": os.environ.get("RIOB_CAMERAS_PORT", "8894"),
            "CAMERAS_DATA_DIR": str(APPS_DIR / "riob-cameras" / "data"),
        },
    },
    "riob-esxi": {
        "cwd": APPS_DIR / "riob-esxi" / "source",
        "script": "app.py",
        "port": int(os.environ.get("RIOB_ESXI_PORT", "8895")),
        "env": {
            "FLASK_RUN_HOST": "127.0.0.1",
            "FLASK_RUN_PORT": os.environ.get("RIOB_ESXI_PORT", "8895"),
            "SECRET_KEY": os.environ.get("RIOB_ESXI_SECRET_KEY", "notechsoft-esxi"),
        },
    },
}
LOCAL_RIOB_ALIASES = {
    "riob-telefonia": ("riob", "#config:sip"),
    "riob-chat-ia": ("riob", "#agentia"),
    "riob-chat": ("riob", "#comunicacao"),
}
_local_riob_lock = threading.Lock()
_local_riob_procs = {}
_app_startup_errors = {}
MENU_SECTIONS = (
    "dashboards",
    "cadastros",
    "ponto",
    "automacao",
    "workflow",
    "compras",
    "estoque",
    "financeiro",
    "relatorios",
    "import_export",
)
_automacao_lock = threading.Lock()
_automacao_proc = None
_nanoponto_lock = threading.Lock()
_nanoponto_proc = None
_zap_lock = threading.Lock()
_zap_proc = None
_nanostore_lock = threading.Lock()
_nanostore_proc = None
_raioxpacs_lock = threading.Lock()
_raioxpacs_proc = None
_finance_state_lock = threading.Lock()
_technology_probe_lock = threading.Lock()
_technology_speed_lock = threading.Lock()
_technology_monitor_lock = threading.Lock()
_technology_monitor_thread = None

TECH_ALERT_DEFAULT_TO = "solucoestecnologicasrenan@gmail.com"
TECH_ALERT_RESOURCES = {
    "CPU": ("cpuPct", "cpu_alerta_pct", "CPU", 90),
    "MEMORIA": ("memoryPct", "memoria_alerta_pct", "memória RAM", 90),
    "DISCO": ("diskPct", "disco_alerta_pct", "disco", 90),
    "REDE": ("networkPct", None, "uso da rede", 90),
    "INTERNET_QUEDA": ("internetDownState", None, "link de internet", 1),
    "LINK_LENTO": ("linkSlowState", None, "velocidade do link", 1),
    "GATEWAY_FALHA": ("gatewayFailureState", None, "gateway", 1),
}


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET") or "notechsoft-dev-secret"

DB_CONFIG = {
    "host": os.environ.get("NS_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("NS_DB_PORT", "3307")),
    "user": os.environ.get("NS_DB_USER", "root"),
    "password": os.environ.get("NS_DB_PASSWORD", ""),
    "database": os.environ.get("NS_DB_NAME", "notechsoft"),
    "charset": "utf8mb4",
    "collation": "utf8mb4_unicode_ci",
    "connection_timeout": int(os.environ.get("NS_DB_CONNECT_TIMEOUT", "10")),
}


def render_db_env_missing():
    return (
        os.environ.get("RENDER") == "true"
        and not os.environ.get("NS_DB_HOST")
        and DB_CONFIG["host"] == "127.0.0.1"
        and DB_CONFIG["port"] == 3307
    )

THEMES = [
    {
        "key": "rio_branco",
        "nome": "Rio Branco",
        "descricao": "Tema operacional laranja, claro e direto.",
        "enabled": True,
    },
    {
        "key": "autoblue",
        "nome": "AutoBlue",
        "descricao": "Tema azul baseado no visual da automacao.",
        "enabled": True,
    },
    {
        "key": "fin-blue",
        "nome": "Fin Blue",
        "descricao": "Tema azul escuro baseado no app financeiro.",
        "enabled": True,
    },
    {
        "key": "pontobege",
        "nome": "Ponto Bege",
        "descricao": "Tema bege baseado no app NanoPonto.",
        "enabled": True,
    },
    {
        "key": "zapgreen",
        "nome": "Zap Green",
        "descricao": "Tema verde escuro baseado no app Zap.",
        "enabled": True,
    },
    {
        "key": "pacsred",
        "nome": "PACS Red",
        "descricao": "Tema vermelho clinico baseado no RaioxPacs.",
        "enabled": True,
    },
]

_db_ready = False


def get_server_conn():
    cfg = DB_CONFIG.copy()
    cfg.pop("database", None)
    return mysql.connector.connect(**cfg)


def get_conn():
    return mysql.connector.connect(**DB_CONFIG)


def ensure_mysql_database(database_name):
    database_name = str(database_name or "").strip()
    if not database_name:
        return
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        raise ValueError(f"nome de banco invalido: {database_name}")

    conn = get_server_conn()
    cur = conn.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    cur.close()
    conn.close()


def ensure_database():
    global _db_ready
    if _db_ready:
        return

    db_name = DB_CONFIG["database"]
    try:
        ensure_mysql_database(db_name)
    except mysql.connector.Error:
        raise

    conn = get_conn()
    cur = conn.cursor()
    schema = (BASE_DIR / "sql" / "schema.sql").read_text(encoding="utf-8")
    for statement in [s.strip() for s in schema.split(";") if s.strip()]:
        cur.execute(statement)

    technology_columns = {
        "enderecos_adicionais": "JSON NULL",
        "download_alerta_mbps": "DECIMAL(10,2) NOT NULL DEFAULT 50",
        "upload_alerta_mbps": "DECIMAL(10,2) NOT NULL DEFAULT 10",
        "cpu_alerta_pct": "DECIMAL(6,2) NOT NULL DEFAULT 90",
        "memoria_alerta_pct": "DECIMAL(6,2) NOT NULL DEFAULT 90",
        "disco_alerta_pct": "DECIMAL(6,2) NOT NULL DEFAULT 90",
        "trafego_alerta_mbps": "DECIMAL(10,2) NOT NULL DEFAULT 100",
        "snmp_community": "VARCHAR(160) NOT NULL DEFAULT ''",
        "snmp_port": "INT NOT NULL DEFAULT 161",
        "agente_porta": "INT NULL",
        "agente_path": "VARCHAR(120) NOT NULL DEFAULT '/metrics'",
    }
    for column_name, column_ddl in technology_columns.items():
        cur.execute(f"SHOW COLUMNS FROM tecnologia_dispositivos LIKE '{column_name}'")
        if not cur.fetchone():
            cur.execute(f"ALTER TABLE tecnologia_dispositivos ADD COLUMN {column_name} {column_ddl}")

    cur.execute("SELECT COUNT(*) FROM tecnologia_dispositivos")
    if int((cur.fetchone() or [0])[0]) == 0:
        cur.executemany(
            """
            INSERT INTO tecnologia_dispositivos
                (nome, tipo, host, porta, sonda, localizacao, observacoes,
                 critico, ativo, latencia_alerta_ms, perda_alerta_pct)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
            """,
            (
                ("Link de internet", "INTERNET", "1.1.1.1", 443, "ICMP", "Internet", "Valida saída TCP, ICMP e resolução DNS.", 1, 80, 5),
                ("Roteador e DHCP", "ROTEADOR", "192.168.200.1", 80, "ICMP", "Rede principal", "Gateway e servidor DHCP da rede 192.168.200.0/24.", 1, 10, 2),
                ("Servidor Ubuntu", "SERVIDOR", "192.168.200.254", 443, "ICMP", "Servidor local", "Host do NanotechSoft e proxy HTTPS.", 1, 10, 2),
                ("Servidor Windows", "SERVIDOR", "192.168.200.121", 445, "ICMP", "Servidor local", "Valida disponibilidade do Windows e do serviço SMB.", 1, 10, 2),
                ("Impressora 138", "IMPRESSORA", "192.168.200.138", 9100, "ICMP", "A identificar", "Detectada com serviço de impressão RAW e LPD.", 0, 20, 5),
                ("Impressora 147", "IMPRESSORA", "192.168.200.147", 9100, "ICMP", "A identificar", "Detectada com serviço de impressão RAW e LPD.", 0, 20, 5),
                ("Impressora 196", "IMPRESSORA", "192.168.200.196", 9100, "ICMP", "A identificar", "Detectada com serviço de impressão RAW.", 0, 20, 5),
            ),
        )

    for seed in (
        ("Relógio ponto", "RELOGIO_PONTO", "192.168.200.110", None, "ICMP", "Rede principal", "Relógio ponto final 110.", 1, 20, 5),
        ("NVR", "NVR", "192.168.200.210", None, "ICMP", "Rede principal", "Gravador de câmeras final 210.", 1, 20, 5),
        ("PC DESKTOP-8VT53SS", "COMPUTADOR", "192.168.200.12", None, "ICMP", "Rede principal", "Windows 10 PC; nome NetBIOS DESKTOP-8VT53SS confirmado na varredura.", 0, 30, 5),
        ("PC RB02", "COMPUTADOR", "192.168.200.21", None, "ICMP", "Rede principal", "Windows 10 PC; nome NetBIOS RB02 confirmado na varredura.", 0, 30, 5),
        ("PC-03", "COMPUTADOR", "192.168.200.136", None, "ICMP", "Rede principal", "Windows 10 PC; nome NetBIOS PC-03 confirmado na varredura.", 0, 30, 5),
        ("PC Linux 184", "COMPUTADOR", "192.168.200.184", 22, "ICMP", "Rede principal", "Linux Debian; SSH e fabricante da placa Elitegroup confirmados na varredura.", 0, 30, 5),
        ("Notebook Renan", "NOTEBOOK", "192.168.200.122", None, "ICMP", "Rede principal", "Notebook Windows 11 informado; nome NetBIOS NOTEBOOK-RENAN confirmado na varredura.", 0, 30, 5),
        ("Notebook WHITEVENDAS", "NOTEBOOK", "192.168.200.197", None, "ICMP", "Rede principal", "Notebook Windows 10 informado; nome NetBIOS WHITEVENDAS confirmado na varredura.", 0, 30, 5),
    ):
        cur.execute(
            """
            SELECT id FROM tecnologia_dispositivos
            WHERE host=%s
               OR JSON_SEARCH(enderecos_adicionais, 'one', %s, NULL, '$[*].host') IS NOT NULL
            LIMIT 1
            """,
            (seed[2], seed[2]),
        )
        if not cur.fetchone():
            cur.execute(
                """
                INSERT INTO tecnologia_dispositivos
                    (nome, tipo, host, porta, sonda, localizacao, observacoes,
                     critico, ativo, latencia_alerta_ms, perda_alerta_pct)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
                """,
                seed,
            )
            if seed[2] == "192.168.200.122":
                cur.execute(
                    """
                    UPDATE tecnologia_dispositivos
                    SET porta=9182, sonda='PROMETHEUS', agente_porta=9182,
                        agente_path='/metrics'
                    WHERE id=%s
                    """,
                    (int(cur.lastrowid),),
                )

    cur.execute("SHOW COLUMNS FROM usuarios LIKE 'nanostore_perfil'")
    if not cur.fetchone():
        cur.execute(
            "ALTER TABLE usuarios ADD COLUMN nanostore_perfil VARCHAR(40) NOT NULL DEFAULT '' AFTER perfil"
        )

    admin_hash = generate_password_hash("admin")
    cur.execute("SELECT id FROM usuarios WHERE login=%s LIMIT 1", ("admin",))
    if not cur.fetchone():
        cur.execute(
            """
            INSERT INTO usuarios (nome, login, senha, perfil, ativo)
            VALUES (%s, %s, %s, %s, %s)
            """,
            ("Administrador", "admin", admin_hash, "admin", 1),
        )

    riob_hash = generate_password_hash("riob")
    cur.execute("SELECT id FROM usuarios WHERE login=%s LIMIT 1", ("riob",))
    riob_row = cur.fetchone()
    if riob_row:
        riob_user_id = int(riob_row[0])
        cur.execute(
            """
            UPDATE usuarios
            SET nome=%s, senha=%s, perfil=%s, ativo=%s
            WHERE id=%s
            """,
            ("Usuario RioB", riob_hash, "usuario", 1, riob_user_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO usuarios (nome, login, senha, perfil, ativo)
            VALUES (%s, %s, %s, %s, %s)
            """,
            ("Usuario RioB", "riob", riob_hash, "usuario", 1),
        )
        riob_user_id = int(cur.lastrowid)

    cur.execute(
        "DELETE FROM usuario_app_permissoes WHERE usuario_id=%s",
        (riob_user_id,),
    )
    cur.execute(
        """
        INSERT INTO usuario_app_permissoes
            (usuario_id, app_key, recurso, permitido)
        VALUES (%s, %s, %s, %s)
        """,
        (riob_user_id, "riob", "*", 1),
    )

    for nome, login, senha in (
        ("Junior", "junior", "junior"),
        ("Rebeca", "rebeca", "rebeca"),
    ):
        senha_hash = generate_password_hash(senha)
        cur.execute("SELECT id FROM usuarios WHERE login=%s LIMIT 1", (login,))
        usuario_row = cur.fetchone()
        if usuario_row:
            usuario_id = int(usuario_row[0])
            cur.execute(
                """
                UPDATE usuarios
                SET nome=%s, senha=%s, perfil=%s, ativo=%s
                WHERE id=%s
                """,
                (nome, senha_hash, "usuario", 1, usuario_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO usuarios (nome, login, senha, perfil, ativo)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (nome, login, senha_hash, "usuario", 1),
            )
            usuario_id = int(cur.lastrowid)

        cur.execute(
            "DELETE FROM usuario_app_permissoes WHERE usuario_id=%s",
            (usuario_id,),
        )
        cur.execute(
            """
            INSERT INTO usuario_app_permissoes
                (usuario_id, app_key, recurso, permitido)
            VALUES (%s, %s, %s, %s)
            """,
            (usuario_id, "riob", "*", 1),
        )

    conn.commit()
    cur.close()
    conn.close()
    _db_ready = True


@app.before_request
def bootstrap_request():
    if request.path.startswith("/static/") or request.path.startswith("/healthz"):
        return
    ensure_database()


@app.after_request
def add_no_cache_headers(resp):
    if (
        request.path.startswith("/api/")
        or request.path.startswith("/apps/tecnologia/api/")
        or request.path in {"/", "/login", "/config"}
    ):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


def _masked_host(value):
    host = str(value or "").strip()
    if not host:
        return ""
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        parts = host.split(".")
        return f"{parts[0]}.{parts[1]}.x.x"
    labels = host.split(".")
    return f"***.{'.'.join(labels[-2:])}" if len(labels) > 2 else "***"


@app.route("/healthz/database")
def healthz_database():
    result = {
        "ok": False,
        "host": _masked_host(DB_CONFIG.get("host")),
        "port": DB_CONFIG.get("port"),
        "portal_schema": DB_CONFIG.get("database"),
        "riob_schema": os.environ.get("RIOB_DB_NAME", "riobranco"),
    }
    started = time.monotonic()
    try:
        with socket.create_connection(
            (DB_CONFIG["host"], int(DB_CONFIG["port"])),
            timeout=3,
        ):
            result["tcp"] = True
        cfg = dict(DB_CONFIG)
        cfg["connection_timeout"] = 5
        conn = mysql.connector.connect(**cfg)
        cur = conn.cursor()
        cur.execute("SELECT DATABASE()")
        result["connected_schema"] = (cur.fetchone() or [""])[0]
        riob_schema = str(result["riob_schema"]).replace("`", "")
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema=%s AND table_name IN ('fretes', 'veiculos')
            """,
            (riob_schema,),
        )
        tables = {row[0] for row in cur.fetchall()}
        result["riob_tables"] = sorted(tables)
        for table in ("fretes", "veiculos"):
            if table in tables:
                cur.execute(f"SELECT COUNT(*) FROM `{riob_schema}`.`{table}`")
                result[f"riob_{table}"] = int((cur.fetchone() or [0])[0])
        cur.close()
        conn.close()
        result["ok"] = {"fretes", "veiculos"}.issubset(tables)
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        errno = getattr(exc, "errno", None)
        if errno is not None:
            result["error_code"] = errno
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return jsonify(result), (200 if result["ok"] else 503)


# ---------------------------------------------------------------------------
# Utilitarios de dominio do portal
# ---------------------------------------------------------------------------
def as_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "sim", "on"}


def public_user(row):
    return {
        "id": int(row["id"]),
        "nome": row.get("nome") or "",
        "login": row.get("login") or "",
        "perfil": row.get("perfil") or "admin",
        "nanostore_perfil": row.get("nanostore_perfil") or "",
    }


def user_is_admin(usuario):
    return (usuario or {}).get("perfil") == "admin"


def get_user_by_login(login):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome, login, senha, perfil, nanostore_perfil, ativo FROM usuarios WHERE login=%s LIMIT 1",
        (login,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def get_user_by_id(user_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome, login, perfil, nanostore_perfil, ativo FROM usuarios WHERE id=%s LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def get_config():
    try:
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT tema FROM portal_config WHERE id=1")
        row = cur.fetchone() or {"tema": "rio_branco"}
        cur.close()
        conn.close()
        return {"tema": row.get("tema") or "rio_branco"}
    except mysql.connector.Error:
        return {"tema": "rio_branco"}


def get_user_permissions(usuario):
    if not usuario or user_is_admin(usuario):
        return {}
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT app_key, recurso
        FROM usuario_app_permissoes
        WHERE usuario_id=%s AND permitido=1
        """,
        (usuario["id"],),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    allowed = {}
    for row in rows:
        allowed.setdefault(row["app_key"], set()).add(row["recurso"])
    return allowed


def can_access(usuario, app_key, recurso=None):
    if user_is_admin(usuario):
        return True
    allowed = get_user_permissions(usuario).get(app_key, set())
    if "*" in allowed:
        return True
    return bool(recurso and recurso in allowed)


def allowed_resources_for_app(usuario, app_key):
    if user_is_admin(usuario):
        return ["*"]
    return sorted(get_user_permissions(usuario).get(app_key, set()))


def set_theme(theme_key):
    enabled_keys = {t["key"] for t in THEMES if t["enabled"]}
    if theme_key not in enabled_keys:
        theme_key = "rio_branco"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO portal_config (id, tema)
        VALUES (1, %s)
        ON DUPLICATE KEY UPDATE tema=VALUES(tema)
        """,
        (theme_key,),
    )
    conn.commit()
    cur.close()
    conn.close()
    return theme_key


# ---------------------------------------------------------------------------
# Descoberta de apps e montagem dos menus dinamicos
# ---------------------------------------------------------------------------
def read_json_file(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def slugify(value):
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-")


def configured_client_id():
    for key in ("CLIENTE_DEPLOY_ID", "CLIENTE_ID", "NANOTECH_CLIENTE_ID"):
        value = os.environ.get(key)
        if value:
            return slugify(value)
    return ""


def client_contracts_updated_at():
    if not CLIENT_CONTRACTS_FILE.exists():
        return None
    return dt.datetime.fromtimestamp(CLIENT_CONTRACTS_FILE.stat().st_mtime, dt.timezone.utc).isoformat()


def normalize_client_module(raw_module):
    if isinstance(raw_module, str):
        raw_module = {"slug": raw_module}
    if not isinstance(raw_module, dict):
        return None
    slug = slugify(raw_module.get("slug") or raw_module.get("id") or raw_module.get("app_key") or raw_module.get("nome"))
    if not slug:
        return None
    return {
        "slug": slug,
        "nome": str(raw_module.get("nome") or raw_module.get("name") or slug).strip(),
        "descricao": str(raw_module.get("descricao") or raw_module.get("description") or "").strip(),
        "href": str(raw_module.get("href") or raw_module.get("url") or "").strip(),
        "status": str(raw_module.get("status") or "contratado").strip() or "contratado",
    }


def normalize_client_contract(raw_client, index=0):
    if not isinstance(raw_client, dict):
        return None
    nome = str(raw_client.get("nome") or raw_client.get("name") or "").strip()
    client_id = slugify(raw_client.get("id") or raw_client.get("slug") or nome)
    if not nome or not client_id:
        return None
    modules = []
    for raw_module in raw_client.get("modules") or raw_client.get("modulos") or []:
        module = normalize_client_module(raw_module)
        if module:
            modules.append(module)
    return {
        "id": client_id,
        "nome": nome,
        "status": str(raw_client.get("status") or "ativo").strip() or "ativo",
        "databaseKey": str(
            raw_client.get("databaseKey")
            or raw_client.get("database")
            or raw_client.get("dbKey")
            or raw_client.get("banco")
            or ""
        ).strip(),
        "observacao": str(raw_client.get("observacao") or raw_client.get("notes") or "").strip(),
        "allModules": as_bool(raw_client.get("allModules", raw_client.get("todosModulos")), False),
        "modules": modules,
        "ordem": int(raw_client.get("ordem") or raw_client.get("order") or index),
    }


def normalize_client_contracts(payload):
    source = payload if isinstance(payload, dict) else {}
    raw_clients = source.get("clients") or source.get("clientes") or []
    clients = []
    seen = set()
    for index, raw_client in enumerate(raw_clients if isinstance(raw_clients, list) else []):
        client = normalize_client_contract(raw_client, index)
        if not client or client["id"] in seen:
            continue
        seen.add(client["id"])
        clients.append(client)
    clients.sort(key=lambda item: (item["ordem"], item["nome"].lower()))
    return {"clients": clients}


def read_client_contracts():
    if not CLIENT_CONTRACTS_FILE.exists():
        return {"clients": []}
    return normalize_client_contracts(read_json_file(CLIENT_CONTRACTS_FILE, {}))


def serialize_client_contracts(state):
    clients = []
    for client in state.get("clients", []):
        item = {
            "id": client["id"],
            "nome": client["nome"],
            "status": client["status"],
            "databaseKey": client["databaseKey"],
            "observacao": client["observacao"],
            "allModules": client["allModules"],
            "modules": [
                {key: value for key, value in module.items() if value not in ("", None)}
                for module in client["modules"]
            ],
        }
        clients.append({key: value for key, value in item.items() if value not in ("", None)})
    return {"clients": clients}


def write_client_contracts(value):
    state = normalize_client_contracts(value)
    CLIENT_CONTRACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CLIENT_CONTRACTS_FILE.with_name(f"{CLIENT_CONTRACTS_FILE.name}.tmp")
    tmp_path.write_text(json.dumps(serialize_client_contracts(state), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(CLIENT_CONTRACTS_FILE)
    return state


def active_client_contract():
    state = read_client_contracts()
    client_id = configured_client_id()
    if client_id:
        return next((client for client in state["clients"] if client["id"] == client_id), None)
    return state["clients"][0] if state["clients"] else None


def apps_liberados_keys():
    if not ALLOWED_APPS_FILE.exists():
        return None
    keys = set()
    for raw in ALLOWED_APPS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keys.add(slugify(line))
    return keys


def normalize_app(item, origem="filesystem"):
    key = str(item.get("app_key") or item.get("key") or "").strip()
    nome = str(item.get("nome") or item.get("name") or key).strip()
    if not key or not nome:
        return None
    return {
        "app_key": key,
        "nome": nome,
        "descricao": str(item.get("descricao") or item.get("description") or "").strip(),
        "url": str(item.get("url") or "").strip() or f"/apps/{key}",
        "standalone_url": str(item.get("standalone_url") or item.get("original_url") or "").strip(),
        "icone": str(item.get("icone") or item.get("icon") or "grid").strip(),
        "ordem": int(item.get("ordem") or item.get("order") or 100),
        "ativo": as_bool(item.get("ativo"), True),
        "origem": origem,
        "temas": item.get("temas") or item.get("themes") or [],
        "menu_groups": item.get("menu_groups") or {},
        "config_groups": item.get("config_groups") or {},
        "workflow_cards": item.get("workflow_cards") or [],
        "source_dir": str(item.get("source_dir") or "").strip(),
    }


def menu_display_name(item, app_name, section=""):
    nome = str(item.get("nome") or "").strip()
    if not nome:
        return app_name

    # O submenu ja informa a area funcional. Remove o nome do app e termos
    # genericos repetidos para produzir itens curtos: em "Dashboards",
    # "Dashboard Financeiro" vira "Financeiro" e "Painel RioB" vira "RioB".
    short_name = re.sub(re.escape(app_name), "", nome, flags=re.I)
    short_name = re.sub(r"\s*[-–—:/|]\s*", " ", short_name)
    short_name = re.sub(r"\s+", " ", short_name).strip()
    generic_by_section = {
        "dashboards": {"dashboard", "painel"},
        "cadastros": {"cadastro", "cadastros"},
        "workflow": {"workflow", "kanban", "fluxo"},
        "compras": {"compra", "compras"},
        "estoque": {"estoque", "estoques"},
        "financeiro": {"financeiro", "financas", "finanças"},
        "relatorios": {"relatorio", "relatorios", "relatório", "relatórios"},
        "import_export": {"import export", "importacao", "importação", "exportacao", "exportação"},
        "config": {"config", "configuracao", "configuração", "configuracoes", "configurações"},
    }
    if not short_name or short_name.casefold() in {
        value.casefold() for value in generic_by_section.get(section, set())
    }:
        return app_name
    return short_name


def current_theme_key():
    return str(get_config().get("tema") or "rio_branco")


def standalone_theme_assets():
    theme = current_theme_key()
    return f"""
<link rel="stylesheet" href="/static/style.css">
<style>
body.theme-rio_branco {{
  --bg: #f4f6f9;
  --panel: #ffffff;
  --panel2: #ffffff;
  --text: #263238;
  --accent2: #c66900;
  --shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
  --radius: 8px;
}}
body.theme-autoblue {{
  --bg: #f4f8fd;
  --panel: #ffffff;
  --panel2: #eef6ff;
  --text: #263238;
  --accent2: #004c99;
  --shadow: 0 2px 8px rgba(0, 51, 102, 0.10);
  --radius: 8px;
}}
body.theme-fin-blue {{
  --bg: #0b1020;
  --panel: #111a33;
  --panel2: #0f1730;
  --text: #e8ecff;
  --accent2: #60a5fa;
  --shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
  --radius: 8px;
}}
body.theme-pontobege {{
  --bg: #f5efe4;
  --panel: rgba(255, 252, 245, 0.96);
  --panel2: #fffaf1;
  --text: #183237;
  --accent2: #bb5b2a;
  --shadow: 0 18px 40px rgba(47, 55, 45, 0.12);
  --radius: 8px;
}}
body.theme-zapgreen {{
  --bg: #07111f;
  --panel: rgba(14, 24, 42, 0.92);
  --panel2: #0d1727;
  --text: #e5eefc;
  --accent2: #25d366;
  --shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
  --radius: 8px;
}}
body.theme-pacsred {{
  --bg: #f6f7f9;
  --panel: rgba(255, 255, 255, 0.96);
  --panel2: #fff1f2;
  --text: #2d3038;
  --accent2: #8f1d2c;
  --shadow: 0 18px 42px rgba(143, 29, 44, 0.12);
  --radius: 8px;
}}
body[class*="theme-"] {{
  --card: var(--panel);
  --btn: var(--accent);
  --btn-hover: var(--accent-dark);
  --bg-2: var(--panel2);
  background: var(--bg);
  color: var(--text);
}}
body[class*="theme-"] .topbar,
body[class*="theme-"] .card,
body[class*="theme-"] .modalCard,
body[class*="theme-"] .modalBox,
body[class*="theme-"] .statusBox,
body[class*="theme-"] .previewBox,
body[class*="theme-"] .sectionBox,
body[class*="theme-"] .diagItem,
body[class*="theme-"] .kpi,
body[class*="theme-"] .item {{
  background: var(--panel);
  border-color: var(--line);
  color: var(--text);
}}
body[class*="theme-"] .sidebar,
body[class*="theme-"] th,
body[class*="theme-"] button,
body[class*="theme-"] .tab.active,
body[class*="theme-"] .btn.primary {{
  background: var(--accent);
  color: #fff;
}}
body[class*="theme-"] .sidebar a:hover,
body[class*="theme-"] button:hover {{
  background: var(--accent-dark);
}}
body[class*="theme-"] .sidebar .menu-section,
body[class*="theme-"] .muted,
body[class*="theme-"] .subtitle,
body[class*="theme-"] .tag-bits {{
  color: var(--muted);
}}
body[class*="theme-"] .tab,
body[class*="theme-"] .btn,
body[class*="theme-"] input,
body[class*="theme-"] select,
body[class*="theme-"] textarea {{
  border-color: var(--line);
}}

/* RioB: adapta o workflow, que originalmente usa cores fixas, ao tema do portal. */
body[class*="theme-"] .menu {{
  background: var(--menu);
}}
body[class*="theme-"] .menu-item:hover {{
  background: var(--menu-hover);
}}
body[class*="theme-"] .menu-item.active {{
  background: var(--menu-active);
}}
body[class*="theme-"] #fretes {{
  color: var(--text);
}}
body[class*="theme-"] #fretes .kanban-col {{
  background: var(--panel2);
  border: 1px solid var(--line);
  color: var(--text);
  box-shadow: var(--shadow);
}}
body[class*="theme-"] #fretes .kanban-col.highlight {{
  background: var(--accent-soft);
  border-color: var(--accent);
}}
body[class*="theme-"] #fretes .card {{
  background: var(--panel);
  border: 1px solid var(--line);
  color: var(--text);
  box-shadow: var(--shadow);
}}
body[class*="theme-"] #fretes .card-info,
body[class*="theme-"] #fretes .details {{
  background: var(--panel2);
  border-color: var(--line);
  color: var(--text);
}}
body[class*="theme-"] #fretes input,
body[class*="theme-"] #fretes select,
body[class*="theme-"] #fretes textarea {{
  background: var(--panel2);
  border-color: var(--line);
  color: var(--text);
}}
body[class*="theme-"] #fretes .kanban-scrollbar {{
  background: var(--panel);
  border-color: var(--line);
}}
body[class*="theme-"] #fretes .kanban::-webkit-scrollbar-thumb,
body[class*="theme-"] #fretes .kanban-scrollbar::-webkit-scrollbar-thumb {{
  background: var(--accent);
}}
</style>
<script>window.NOTECHSOFT_THEME = {json.dumps(theme)};</script>
"""


def inject_before_body_close(document, snippet):
    if not snippet:
        return document
    match = re.search(r"</body\s*>", document, flags=re.I)
    if not match:
        return document + "\n" + snippet
    return document[: match.start()] + snippet + "\n" + document[match.start() :]


def apply_standalone_theme(document):
    theme = current_theme_key()
    if "</head>" in document:
        document = document.replace("</head>", standalone_theme_assets() + "\n</head>", 1)
    else:
        document = standalone_theme_assets() + document

    body_match = re.search(r"<body([^>]*)>", document, flags=re.I)
    if not body_match:
        return document
    attrs = body_match.group(1)
    class_match = re.search(r'class=(["\'])(.*?)\1', attrs, flags=re.I | re.S)
    if class_match:
        classes = class_match.group(2).split()
        classes = [item for item in classes if not item.startswith("theme-")]
        classes.append(f"theme-{theme}")
        new_attrs = (
            attrs[: class_match.start()]
            + f'class="{html_lib.escape(" ".join(classes))}"'
            + attrs[class_match.end() :]
        )
    else:
        new_attrs = attrs + f' class="theme-{html_lib.escape(theme)}"'
    return document[: body_match.start()] + f"<body{new_attrs}>" + document[body_match.end() :]


def allowed_app_keys():
    """Retorna os apps liberados para o deploy atual."""
    client_id = configured_client_id()
    if not client_id:
        return apps_liberados_keys()

    client = active_client_contract()
    if client is None:
        return set()
    if client.get("allModules"):
        return None
    return {module["slug"] for module in client.get("modules") or [] if module.get("status") != "importar"}


def filesystem_apps():
    """Carrega manifests de apps em apps/manifest.json e apps/*/app.json."""
    apps = []
    root_manifest = read_json_file(APPS_DIR / "manifest.json", [])
    if isinstance(root_manifest, list):
        for item in root_manifest:
            app_item = normalize_app(item, "manifest")
            if app_item:
                apps.append(app_item)

    for child in sorted(APPS_DIR.iterdir() if APPS_DIR.exists() else []):
        manifest = child / "app.json"
        if child.is_dir() and manifest.exists():
            app_item = normalize_app(read_json_file(manifest, {}), "filesystem")
            if app_item:
                apps.append(app_item)
    return apps


def database_apps():
    try:
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT app_key, nome, descricao, url, icone, ativo, ordem, origem
            FROM installed_apps
            ORDER BY ordem, nome
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [normalize_app(row, row.get("origem") or "database") for row in rows]
    except mysql.connector.Error:
        return []


def all_portal_apps():
    merged = {}
    for item in database_apps() + filesystem_apps():
        if item and item["ativo"]:
            merged[item["app_key"]] = item
    return sorted(merged.values(), key=lambda x: (x["ordem"], x["nome"].lower()))


def list_apps():
    allowed = allowed_app_keys()
    return [item for item in all_portal_apps() if allowed is None or item["app_key"] in allowed]


def app_catalog():
    catalog = {}
    for app_item in all_portal_apps():
        catalog[app_item["app_key"]] = {
            "slug": app_item["app_key"],
            "nome": app_item["nome"],
            "descricao": app_item["descricao"],
            "href": app_item.get("standalone_url") or app_item["url"],
            "status": "disponivel",
        }
    return catalog


def enrich_client_module(module, catalog):
    catalog_item = catalog.get(module["slug"], {})
    return {
        "slug": module["slug"],
        "nome": module["nome"] or catalog_item.get("nome") or module["slug"],
        "descricao": module["descricao"] or catalog_item.get("descricao") or "",
        "href": module["href"] or catalog_item.get("href") or "",
        "status": module["status"] or "contratado",
    }


def client_contracts_payload():
    state = read_client_contracts()
    catalog = app_catalog()
    for client in state["clients"]:
        for module in client["modules"]:
            if module["slug"] not in catalog:
                catalog[module["slug"]] = {
                    "slug": module["slug"],
                    "nome": module["nome"] or module["slug"],
                    "descricao": module["descricao"],
                    "href": module["href"],
                    "status": module["status"],
                }

    clients = []
    for client in state["clients"]:
        if client["allModules"]:
            modules = [
                {**module, "status": "contratado"}
                for module in catalog.values()
                if module.get("href")
            ]
        else:
            modules = [enrich_client_module(module, catalog) for module in client["modules"]]
        clients.append(
            {
                "id": client["id"],
                "nome": client["nome"],
                "status": client["status"],
                "databaseKey": client["databaseKey"],
                "observacao": client["observacao"],
                "allModules": client["allModules"],
                "modules": modules,
            }
        )

    selected_id = configured_client_id()
    active = next((client for client in clients if client["id"] == selected_id), None) if selected_id else (clients[0] if clients else None)
    missing = bool(selected_id and active is None)
    return {
        "clients": clients,
        "catalog": list(catalog.values()),
        "activeClient": active,
        "activeClientId": active["id"] if active else "",
        "configuredClientId": selected_id,
        "configuredClientMissing": missing,
        "selectedByEnv": bool(selected_id),
        "source": {"type": "file", "path": CLIENT_CONTRACTS_FILE.name},
        "updatedAt": client_contracts_updated_at(),
    }


def find_client_index(state, client_id):
    safe_id = slugify(client_id)
    for index, client in enumerate(state["clients"]):
        if client["id"] == safe_id:
            return index
    return -1


def normalize_single_client(payload):
    client = normalize_client_contract(payload)
    if not client:
        raise ValueError("informe nome e ID validos do cliente")
    return client


def create_client_contract(payload):
    state = read_client_contracts()
    client = normalize_single_client(payload)
    if find_client_index(state, client["id"]) >= 0:
        raise ValueError("cliente ja cadastrado")
    state["clients"].append(client)
    write_client_contracts(state)


def update_client_contract(client_id, payload):
    state = read_client_contracts()
    index = find_client_index(state, client_id)
    if index < 0:
        raise LookupError("cliente nao encontrado")
    data = payload if isinstance(payload, dict) else {}
    data.setdefault("id", state["clients"][index]["id"])
    client = normalize_single_client(data)
    duplicate_index = find_client_index(state, client["id"])
    if duplicate_index >= 0 and duplicate_index != index:
        raise ValueError("ja existe outro cliente com este ID")
    state["clients"][index] = client
    write_client_contracts(state)


def delete_client_contract(client_id):
    state = read_client_contracts()
    index = find_client_index(state, client_id)
    if index < 0:
        raise LookupError("cliente nao encontrado")
    del state["clients"][index]
    write_client_contracts(state)


def app_visible_to_user(app_item, usuario):
    if user_is_admin(usuario):
        return True
    permissions = get_user_permissions(usuario).get(app_item["app_key"], set())
    return bool(permissions)


PUBLIC_APP_PATH_PREFIXES = (
    "/apps/zap/webhooks/whatsapp",
    "/apps/zap/public/uploads/",
    "/apps/pacs/static/",
    "/apps/pacs/share/",
    "/apps/pacs/api/share/",
)


@app.before_request
def enforce_app_permission():
    path = request.path
    if not path.startswith("/apps/"):
        return None
    if any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in PUBLIC_APP_PATH_PREFIXES):
        return None

    app_key = path.removeprefix("/apps/").split("/", 1)[0].strip()
    if not app_key:
        return None

    usuario = current_user_or_logout()
    if not usuario:
        if path.startswith("/apps/tecnologia/api/"):
            return jsonify({"erro": "login necessário"}), 401
        return redirect(url_for("login_page"))
    if not app_visible_to_user({"app_key": app_key}, usuario):
        return jsonify({"erro": "app nao liberado para este usuario"}), 403
    return None


def visible_apps_for_user(usuario):
    apps = list_apps()
    if user_is_admin(usuario):
        return apps
    permissions = get_user_permissions(usuario)
    return [
        app_item
        for app_item in apps
        if permissions.get(app_item["app_key"])
    ]


def menu_item_visible(item, app_item, usuario):
    if user_is_admin(usuario):
        return True
    recurso = item.get("recurso") or item.get("permission")
    return can_access(usuario, app_item["app_key"], recurso)


def menu_sections(apps, usuario=None):
    """Agrupa atalhos dos manifests nos menus principais da plataforma."""
    sections = {section: [] for section in MENU_SECTIONS}
    sections["config"] = []
    for app_item in apps:
        if not app_visible_to_user(app_item, usuario):
            continue
        groups = app_item.get("menu_groups") or {}
        config_groups = app_item.get("config_groups") or {}
        for section in MENU_SECTIONS:
            for item in groups.get(section, []):
                if menu_item_visible(item, app_item, usuario):
                    sections[section].append(
                        {
                            **item,
                            "nome": menu_display_name(item, app_item["nome"], section),
                            "app": app_item["nome"],
                            "grupo": item.get("grupo") or "",
                        }
                    )
        for group_items in config_groups.values():
            for item in group_items:
                if menu_item_visible(item, app_item, usuario):
                    sections["config"].append(
                        {
                            **item,
                            "nome": menu_display_name(item, app_item["nome"], "config"),
                            "app": app_item["nome"],
                            "grupo": item.get("grupo") or "",
                        }
                    )
    return sections


def workflow_board_for_app(app_key, usuario):
    apps = list_apps()
    app_item = next((item for item in apps if item["app_key"] == app_key), None)
    if not app_item or not app_visible_to_user(app_item, usuario):
        return None
    cards = []
    for item in app_item.get("workflow_cards") or []:
        if menu_item_visible(item, app_item, usuario):
            cards.append({**item, "app": app_item["nome"]})
    if not cards:
        for item in (app_item.get("menu_groups") or {}).get("workflow", []):
            if menu_item_visible(item, app_item, usuario):
                cards.append({**item, "app": app_item["nome"]})
    return {
        "app": app_item,
        "cards": cards,
    }


# ---------------------------------------------------------------------------
# Autenticacao e contexto de telas
# ---------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("usuario_id"):
            if request.path.startswith("/api/"):
                return jsonify({"erro": "login necessario"}), 401
            return redirect(url_for("login_page"))
        return view(*args, **kwargs)

    return wrapped


def current_user_or_logout():
    user_id = session.get("usuario_id")
    if not user_id:
        return None
    user = get_user_by_id(user_id)
    if not user or int(user.get("ativo") or 0) != 1:
        session.clear()
        return None
    return public_user(user)


def portal_context(usuario=None):
    usuario = usuario or current_user_or_logout()
    apps = list_apps()
    visible_apps = visible_apps_for_user(usuario)
    client_config = client_contracts_payload()
    return {
        "usuario": usuario,
        "apps": visible_apps,
        "menu": menu_sections(apps, usuario),
        "config": get_config(),
        "themes": THEMES,
        "client_config": client_config,
        "active_client": client_config["activeClient"],
    }


@app.route("/login")
def login_page():
    if session.get("usuario_id"):
        return redirect(url_for("portal"))
    return render_template("login.html", config=get_config(), themes=THEMES)


@app.route("/")
@login_required
def portal():
    usuario = current_user_or_logout()
    if not usuario:
        return redirect(url_for("login_page"))
    return render_template(
        "portal.html",
        **portal_context(usuario),
    )


@app.route("/config")
@login_required
def config_page():
    return render_template(
        "config.html",
        **portal_context(),
    )


def quoted_identifier(name):
    name = str(name or "")
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError(f"identificador invalido: {name}")
    return f"`{name}`"


def json_safe_value(value):
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"__bytes_b64": base64.b64encode(value).decode("ascii")}
    return value


def restore_value(value):
    if isinstance(value, dict) and set(value.keys()) == {"__bytes_b64"}:
        return base64.b64decode(value["__bytes_b64"])
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def current_database_tables(cur):
    cur.execute(
        """
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
        """
    )
    return [row["TABLE_NAME"] if isinstance(row, dict) else row[0] for row in cur.fetchall()]


def table_columns(cur, table):
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table,),
    )
    return [row["COLUMN_NAME"] if isinstance(row, dict) else row[0] for row in cur.fetchall()]


def export_portal_backup():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    tables = current_database_tables(cur)
    backup_tables = {}
    counts = {}
    for table in tables:
        cur.execute(f"SELECT * FROM {quoted_identifier(table)}")
        rows = []
        for row in cur.fetchall():
            rows.append({key: json_safe_value(value) for key, value in row.items()})
        backup_tables[table] = rows
        counts[table] = len(rows)
    cur.close()
    conn.close()
    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "database": DB_CONFIG["database"],
        "tables": backup_tables,
        "counts": counts,
    }


def restore_portal_backup(payload):
    if not isinstance(payload, dict):
        raise ValueError("backup invalido")
    if payload.get("format") != BACKUP_FORMAT:
        raise ValueError("arquivo nao e um backup do portal NanotechSoft")
    if int(payload.get("version") or 0) != BACKUP_VERSION:
        raise ValueError("versao de backup nao suportada")
    backup_tables = payload.get("tables")
    if not isinstance(backup_tables, dict):
        raise ValueError("backup sem tabelas")

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    restored = {}
    try:
        current_tables = current_database_tables(cur)
        target_tables = [table for table in current_tables if table in backup_tables]
        if not target_tables:
            raise ValueError("backup nao contem tabelas compativeis com o banco atual")

        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        for table in reversed(target_tables):
            cur.execute(f"DELETE FROM {quoted_identifier(table)}")

        for table in target_tables:
            rows = backup_tables.get(table)
            if not isinstance(rows, list):
                raise ValueError(f"tabela {table} invalida no backup")
            columns = table_columns(cur, table)
            count = 0
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"linha invalida na tabela {table}")
                values = {column: restore_value(row[column]) for column in columns if column in row}
                if not values:
                    continue
                cols_sql = ", ".join(quoted_identifier(column) for column in values)
                placeholders = ", ".join(["%s"] * len(values))
                cur.execute(
                    f"INSERT INTO {quoted_identifier(table)} ({cols_sql}) VALUES ({placeholders})",
                    tuple(values.values()),
                )
                count += 1
            restored[table] = count

        cur.execute("SET FOREIGN_KEY_CHECKS=1")
        conn.commit()
    except Exception:
        conn.rollback()
        try:
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
        except Exception:
            pass
        raise
    finally:
        cur.close()
        conn.close()
    return restored


def current_admin_or_json_error():
    usuario = current_user_or_logout()
    if not usuario:
        return None, (jsonify({"erro": "login necessario"}), 401)
    if not user_is_admin(usuario):
        return None, (jsonify({"erro": "somente administradores podem usar esta area"}), 403)
    return usuario, None


NANOSTORE_USER_PROFILES = {
    "pharmacy": "Farmacia",
    "store": "Loja",
    "distributor": "Distribuidora",
    "commerce": "Comercio",
    "food": "Alimentos",
    "services": "Prestador de servicos",
}


def portal_users_payload():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT id, nome, login, perfil, nanostore_perfil, ativo
        FROM usuarios
        ORDER BY nome, login
        """
    )
    users = []
    for row in cur.fetchall():
        item = public_user(row)
        item["ativo"] = bool(row.get("ativo"))
        users.append(item)
    cur.close()
    conn.close()
    return {
        "ok": True,
        "usuarios": users,
        "nanostore_perfis": [
            {"key": key, "name": name}
            for key, name in NANOSTORE_USER_PROFILES.items()
        ],
    }


@app.route("/api/usuarios")
@login_required
def api_users():
    _, error = current_admin_or_json_error()
    if error:
        return error
    return jsonify(portal_users_payload())


@app.route("/api/usuarios/<int:user_id>", methods=["PUT"])
@login_required
def api_update_user(user_id):
    admin, error = current_admin_or_json_error()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    nome = str(payload.get("nome") or "").strip()
    login = str(payload.get("login") or "").strip().lower()
    perfil = str(payload.get("perfil") or "usuario").strip().lower()
    nanostore_perfil = str(payload.get("nanostore_perfil") or "").strip().lower()
    senha = str(payload.get("senha") or "")
    ativo = as_bool(payload.get("ativo"), True)

    if not nome:
        return jsonify({"erro": "informe o nome do usuario"}), 400
    if not re.fullmatch(r"[a-z0-9._-]{3,80}", login):
        return jsonify({"erro": "login deve ter de 3 a 80 letras, numeros, ponto, hifen ou sublinhado"}), 400
    if perfil not in {"admin", "usuario"}:
        return jsonify({"erro": "perfil de acesso invalido"}), 400
    if nanostore_perfil and nanostore_perfil not in NANOSTORE_USER_PROFILES:
        return jsonify({"erro": "perfil do NanoStore invalido"}), 400
    if senha and len(senha) < 4:
        return jsonify({"erro": "a nova senha deve ter ao menos 4 caracteres"}), 400
    if int(admin["id"]) == user_id and (perfil != "admin" or not ativo):
        return jsonify({"erro": "o administrador conectado nao pode remover o proprio acesso"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM usuarios WHERE id=%s LIMIT 1", (user_id,))
        if not cur.fetchone():
            return jsonify({"erro": "usuario nao encontrado"}), 404
        cur.execute("SELECT id FROM usuarios WHERE login=%s AND id<>%s LIMIT 1", (login, user_id))
        if cur.fetchone():
            return jsonify({"erro": "este login ja esta em uso"}), 409

        fields = ["nome=%s", "login=%s", "perfil=%s", "nanostore_perfil=%s", "ativo=%s"]
        values = [nome, login, perfil, nanostore_perfil, int(ativo)]
        if senha:
            fields.append("senha=%s")
            values.append(generate_password_hash(senha))
        values.append(user_id)
        cur.execute(f"UPDATE usuarios SET {', '.join(fields)} WHERE id=%s", tuple(values))

        cur.execute("DELETE FROM usuario_app_permissoes WHERE usuario_id=%s", (user_id,))
        if perfil != "admin" and nanostore_perfil:
            cur.execute(
                """
                INSERT INTO usuario_app_permissoes (usuario_id, app_key, recurso, permitido)
                VALUES (%s, 'nanostore', '*', 1)
                """,
                (user_id,),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return jsonify(portal_users_payload())


@app.route("/api/backup/export")
@login_required
def api_backup_export():
    _, error = current_admin_or_json_error()
    if error:
        return error
    backup = export_portal_backup()
    body = json.dumps(backup, ensure_ascii=False, indent=2)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"nanotechsoft-backup_{timestamp}.json"
    return Response(
        body,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/api/backup/import", methods=["POST"])
@login_required
def api_backup_import():
    _, error = current_admin_or_json_error()
    if error:
        return error
    try:
        if request.is_json:
            payload = request.get_json(silent=False)
        else:
            file = request.files.get("backup")
            if not file:
                return jsonify({"erro": "envie um arquivo de backup"}), 400
            raw = file.read(MAX_BACKUP_BYTES + 1)
            if len(raw) > MAX_BACKUP_BYTES:
                return jsonify({"erro": "arquivo de backup muito grande"}), 413
            payload = json.loads(raw.decode("utf-8-sig"))
        restored = restore_portal_backup(payload)
        return jsonify({"ok": True, "restored": restored})
    except json.JSONDecodeError:
        return jsonify({"erro": "JSON invalido"}), 400
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400


@app.route("/workflow/<app_key>")
@login_required
def workflow_kanban_page(app_key):
    usuario = current_user_or_logout()
    board = workflow_board_for_app(app_key, usuario)
    if not board:
        return jsonify({"erro": "workflow nao encontrado"}), 404
    return render_template(
        "workflow_kanban.html",
        active_page="workflow",
        board=board,
        **portal_context(usuario),
    )


def riob_app_path(app_key, subpath=""):
    default = RIOB_ROUTE_DEFAULTS.get(app_key, "/")
    if subpath:
        return "/" + subpath.lstrip("/")
    return default


def rewrite_riob_location(value, prefix="/apps/riob"):
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme and parsed.netloc:
        if value.startswith(RIOB_BASE_URL):
            path = parsed.path or "/"
            return prefix + path + (("?" + parsed.query) if parsed.query else "")
        return value
    if value.startswith(prefix):
        return value
    if value.startswith("/apps/"):
        return value
    if value.startswith("/"):
        return prefix + value
    return value


def rewrite_riob_html(content, prefix="/apps/riob"):
    text = content.decode("utf-8", errors="replace")
    replacements = {
        'href="/': f'href="{prefix}/',
        "href='/": f"href='{prefix}/",
        'src="/': f'src="{prefix}/',
        "src='/": f"src='{prefix}/",
        'action="/': f'action="{prefix}/',
        "action='/": f"action='{prefix}/",
        'fetch("/': f'fetch("{prefix}/',
        "fetch('/": f"fetch('{prefix}/",
        'window.open("/': f'window.open("{prefix}/',
        "window.open('/": f"window.open('{prefix}/",
        '"/api/': f'"{prefix}/api/',
        "'/api/": f"'{prefix}/api/",
        "`/api/": f"`{prefix}/api/",
        '"/monitor/': f'"{prefix}/monitor/',
        "'/monitor/": f"'{prefix}/monitor/",
        "`/monitor/": f"`{prefix}/monitor/",
        '"/importar-xml/': f'"{prefix}/importar-xml/',
        "'/importar-xml/": f"'{prefix}/importar-xml/",
        "`/importar-xml/": f"`{prefix}/importar-xml/",
        '"/gestor-emails/': f'"{prefix}/gestor-emails/',
        "'/gestor-emails/": f"'{prefix}/gestor-emails/",
        "`/gestor-emails/": f"`{prefix}/gestor-emails/",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)

    text = inject_before_body_close(text, riob_hash_bridge_script())
    return apply_standalone_theme(text).encode("utf-8")


def riob_hash_bridge_script():
    return """
<script>
(function() {
  function openFromHash() {
    var hash = (window.location.hash || "").replace(/^#/, "");
    if (!hash) return;
    var parts = hash.split(":");
    var section = parts[0] || "";
    var view = parts[1] || "";
    try {
      if (section === "config" && view && typeof window.openConfigView === "function") {
        window.openConfigView(null, view);
        return;
      }
      if (section === "monitor" && view && typeof window.openMonitorView === "function") {
        window.openMonitorView(null, view);
        return;
      }
      if (section === "dashboard" && view && typeof window.openDashboardView === "function") {
        window.openDashboardView(null, view);
        return;
      }
      if (section === "cadastros" && view && typeof window.openCadastrosView === "function") {
        window.openCadastrosView(null, view);
        return;
      }
      if (section === "comissao" && ["relatorios", "exportar"].includes(view) && typeof window.openComissaoView === "function") {
        window.openComissaoView(null, view);
        return;
      }
      if (section === "comissao" && typeof window.openWorkflowView === "function") {
        window.openWorkflowView(null, "comissao");
        return;
      }
      if (section === "gestaofrota" && view && typeof window.openGestaoFrotaView === "function") {
        if (view === "cargas" && typeof window.openGestaoFrotaCargas === "function") {
          window.openGestaoFrotaCargas(null);
          return;
        }
        if (view === "escala" && typeof window.openGestaoFrotaEscala === "function") {
          window.openGestaoFrotaEscala(null);
          return;
        }
        window.openGestaoFrotaView(null, view);
        return;
      }
      if (section === "workflow" && view && typeof window.openWorkflowView === "function") {
        window.openWorkflowView(null, view);
        return;
      }
      if (section === "vendas" && view && typeof window.openVendasView === "function") {
        if (view === "comissao" && typeof window.openVendasComissao === "function") {
          window.openVendasComissao(null);
          return;
        }
        if (["importar", "vendas_diario_importar", "importar_vendas_diario"].includes(view) && typeof window.openWorkflowView === "function") {
          window.openWorkflowView(null, "vendas_diario_importar");
          return;
        }
        if (["diario", "vendas_diario", "kanban"].includes(view) && typeof window.openWorkflowView === "function") {
          window.openWorkflowView(null, "vendas_diario");
          return;
        }
        window.openVendasView(null, view);
        return;
      }
      if (section === "estoque" && typeof window.openEstoqueView === "function") {
        if (view === "importar_xml" && typeof window.openComprasView === "function") {
          window.openComprasView(null, "importar_xml_bipe");
          return;
        }
        if (["importar_xml_bipe", "importar_xml_auto"].includes(view) && typeof window.openComprasView === "function") {
          window.openComprasView(null, view);
          return;
        }
        window.openEstoqueView(null, view || "posicao");
        return;
      }
      if (section && typeof window.showTab === "function") {
        window.showTab(section, document.querySelector('[data-tab="' + section + '"]'));
      }
    } catch (err) {
      console.warn("NanotechSoft RioB hash bridge:", err);
    }
  }
  window.addEventListener("load", function() { setTimeout(openFromHash, 250); });
  window.addEventListener("hashchange", openFromHash);
})();
</script>
"""


def rewrite_riob_javascript(content, prefix="/apps/riob"):
    text = content.decode("utf-8", errors="replace")
    replacements = {
        '"/api/': f'"{prefix}/api/',
        "'/api/": f"'{prefix}/api/",
        "`/api/": f"`{prefix}/api/",
        '"/monitor/': f'"{prefix}/monitor/',
        "'/monitor/": f"'{prefix}/monitor/",
        "`/monitor/": f"`{prefix}/monitor/",
        '"/importar-xml/': f'"{prefix}/importar-xml/',
        "'/importar-xml/": f"'{prefix}/importar-xml/",
        "`/importar-xml/": f"`{prefix}/importar-xml/",
        '"/gestor-emails/': f'"{prefix}/gestor-emails/',
        "'/gestor-emails/": f"'{prefix}/gestor-emails/",
        "`/gestor-emails/": f"`{prefix}/gestor-emails/",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.encode("utf-8")


def open_riob_request(req, timeout=120):
    if RIOB_SSL_VERIFY:
        return urllib.request.urlopen(req, timeout=timeout)
    context = ssl._create_unverified_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPRedirectHandler(),
    )
    return opener.open(req, timeout=timeout)


@app.route("/healthz/riob")
def healthz_riob():
    if not RIOB_BASE_URL:
        return jsonify({
            "ok": False,
            "mode": "proxy_only",
            "error_type": "ConfigurationError",
            "message": "RIOB_BASE_URL externa nao configurada.",
        }), 503
    parsed = urllib.parse.urlparse(RIOB_BASE_URL)
    result = {
        "ok": False,
        "origin_host": _masked_host(parsed.hostname),
        "origin_port": parsed.port,
        "origin_scheme": parsed.scheme,
        "mode": "local" if parsed.hostname in {"127.0.0.1", "localhost", "::1"} else "proxy",
    }
    started = time.monotonic()
    try:
        req = urllib.request.Request(
            f"{RIOB_BASE_URL}/api/status",
            headers={"Accept": "application/json"},
        )
        with open_riob_request(req, timeout=15) as resp:
            result["upstream_status"] = resp.status
            result["ok"] = 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        result["upstream_status"] = exc.code
        result["error_type"] = type(exc).__name__
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        result["error_type"] = type(exc).__name__
        result["network_error"] = type(reason).__name__ if reason is not None else "Unknown"
        errno = getattr(reason, "errno", None)
        if errno is not None:
            result["network_errno"] = errno
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return jsonify(result), (200 if result["ok"] else 503)


def local_riob_prefix(app_key):
    return f"/apps/{app_key}/riob"


def rewrite_local_riob_location(value, app_key):
    prefix = local_riob_prefix(app_key)
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme and parsed.netloc:
        return prefix + (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
    if value.startswith(prefix):
        return value
    if value.startswith("/apps/"):
        return value
    if value.startswith("/"):
        return prefix + value
    return value


def rewrite_local_riob_text(content, app_key, apply_theme=False):
    prefix = local_riob_prefix(app_key)
    text = content.decode("utf-8", errors="replace")
    replacements = {
        'href="/': f'href="{prefix}/',
        "href='/": f"href='{prefix}/",
        'src="/': f'src="{prefix}/',
        "src='/": f"src='{prefix}/",
        'action="/': f'action="{prefix}/',
        "action='/": f"action='{prefix}/",
        'fetch("/': f'fetch("{prefix}/',
        "fetch('/": f"fetch('{prefix}/",
        'window.open("/': f'window.open("{prefix}/',
        "window.open('/": f"window.open('{prefix}/",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    # Rotas absolutas de outros aplicativos do Portal nao recebem o prefixo
    # do app local atual (por exemplo, /apps/riob-email/riob/).
    text = text.replace(f"{prefix}/apps/", "/apps/")
    if apply_theme:
        if app_key == "riob":
            text = inject_before_body_close(text, riob_hash_bridge_script())
        text = apply_standalone_theme(text)
    return text.encode("utf-8")


def ensure_local_riob_app(app_key):
    cfg = LOCAL_RIOB_APPS.get(app_key)
    if not cfg:
        log_app_startup_error(app_key, "configuracao local do app nao encontrada")
        return False
    port = int(cfg["port"])
    if tcp_open("127.0.0.1", port):
        _app_startup_errors.pop(app_key, None)
        return True

    with _local_riob_lock:
        if tcp_open("127.0.0.1", port):
            _app_startup_errors.pop(app_key, None)
            return True
        proc = _local_riob_procs.get(app_key)
        if proc is not None and proc.poll() is None:
            time.sleep(0.5)
            ok = tcp_open("127.0.0.1", port)
            if ok:
                _app_startup_errors.pop(app_key, None)
            return ok

        cwd = Path(cfg["cwd"])
        script = cwd / str(cfg["script"])
        if not script.exists():
            log_app_startup_error(app_key, f"codigo nao encontrado em {script}")
            return False

        app_env = {key: str(value) for key, value in (cfg.get("env") or {}).items()}
        database_name = app_env.get("DB_NAME")
        if database_name:
            try:
                ensure_mysql_database(database_name)
            except Exception as exc:
                log_app_startup_error(app_key, f"falha ao preparar banco {database_name}: {exc}")
                return False

        python_bin = BASE_DIR / ".venv" / "bin" / "python"
        if not python_bin.exists():
            python_bin = Path(sys.executable)

        env = os.environ.copy()
        env.pop("WERKZEUG_SERVER_FD", None)
        env.pop("WERKZEUG_RUN_MAIN", None)
        env.update(app_env)
        env.setdefault("PYTHONUNBUFFERED", "1")

        try:
            log_path = BASE_DIR / f"{app_key}.log"
            log_file = log_path.open("ab")
            _local_riob_procs[app_key] = subprocess.Popen(
                [str(python_bin), str(script.name)],
                cwd=str(cwd),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            log_app_startup_error(app_key, exc)
            return False
        startup_wait = float(cfg.get("startup_wait") or 15)
        attempts = max(1, int(startup_wait / 0.25))
        for _ in range(attempts):
            if tcp_open("127.0.0.1", port):
                _app_startup_errors.pop(app_key, None)
                return True
            time.sleep(0.25)
        log_app_startup_error(app_key, f"processo iniciou, mas a porta 127.0.0.1:{port} nao respondeu")
    return False


def warmup_render_riob():
    """Inicia o RioB antes do primeiro acesso quando ele compartilha o container."""
    render_runtime = str(os.environ.get("RENDER") or "").strip().lower() == "true"
    riob_target = urllib.parse.urlparse(RIOB_BASE_URL)
    if not render_runtime or riob_target.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return
    threading.Thread(
        target=ensure_local_riob_app,
        args=("riob",),
        name="riob-render-warmup",
        daemon=True,
    ).start()


def local_riob_proxy_response(app_key, subpath=""):
    usuario = current_user_or_logout()
    if not usuario:
        return redirect(url_for("login_page"))
    if not app_visible_to_user({"app_key": app_key}, usuario):
        return jsonify({"erro": "app nao liberado para este usuario"}), 403
    if not ensure_local_riob_app(app_key):
        return render_template(
            "app_placeholder.html",
            app_key=app_key,
            mensagem=app_startup_message(app_key, f"Nao foi possivel iniciar o modulo local {app_key}."),
            **portal_context(usuario),
        ), 502

    port = LOCAL_RIOB_APPS[app_key]["port"]
    upstream_path = "/" + (subpath or "").lstrip("/")
    query = request.query_string.decode("utf-8", errors="ignore")
    upstream_url = f"http://127.0.0.1:{port}{upstream_path}"
    if query:
        upstream_url += "?" + query

    headers = {}
    for key, value in request.headers.items():
        if key.lower() in {"host", "connection", "content-length", "accept-encoding"}:
            continue
        headers[key] = value
    headers["X-Usuario-Id"] = str(usuario["id"])
    headers["X-Usuario-Nome"] = usuario.get("nome") or usuario.get("login") or ""
    headers["X-Usuario-Login"] = usuario["login"]
    headers["X-Usuario-Perfil"] = usuario.get("perfil") or "usuario"
    headers["X-Forwarded-Prefix"] = f"/apps/{app_key}"
    data = request.get_data() if request.method in {"POST", "PUT", "PATCH"} else None
    req = urllib.request.Request(upstream_url, data=data, headers=headers, method=request.method)

    # O redirecionamento precisa voltar ao navegador para que uma rota de outro
    # modulo (por exemplo, XML -> Gestor de E-mails) seja processada novamente
    # pelo Portal. O urlopen padrao segue o Location dentro do processo atual e
    # transforma /apps/riob-email/... em uma requisicao indevida ao app XML.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, redirect_req, fp, code, msg, redirect_headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)

    try:
        with opener.open(req, timeout=120) as resp:
            body = resp.read()
            status = resp.status
            resp_headers = resp.headers
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
        resp_headers = exc.headers
    except Exception as exc:
        return render_template(
            "app_placeholder.html",
            app_key=app_key,
            mensagem=f"Nao foi possivel acessar o modulo local {app_key}: {exc}",
            **portal_context(usuario),
        ), 502

    content_type = resp_headers.get("Content-Type") or mimetypes.guess_type(upstream_path)[0] or "application/octet-stream"
    if "text/html" in content_type:
        body = rewrite_local_riob_text(body, app_key, apply_theme=True)
    elif "javascript" in content_type or upstream_path.endswith((".js", ".css")):
        body = rewrite_local_riob_text(body, app_key)

    response = Response(body, status=status, content_type=content_type)
    excluded = {
        "connection",
        "content-encoding",
        "content-length",
        "transfer-encoding",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "upgrade",
    }
    for key, value in resp_headers.items():
        lk = key.lower()
        if lk in excluded:
            continue
        if lk == "location":
            value = rewrite_local_riob_location(value, app_key)
        response.headers[key] = value
    return response


def riob_proxy_response(app_key="riob", subpath="", embedded=False):
    usuario = current_user_or_logout()
    if not usuario:
        return redirect(url_for("login_page"))
    if not app_visible_to_user({"app_key": app_key}, usuario):
        return jsonify({"erro": "app nao liberado para este usuario"}), 403
    if not RIOB_BASE_URL:
        return render_template(
            "app_placeholder.html",
            app_key=app_key,
            mensagem="Portal em modo proxy: configure uma origem HTTPS externa em RIOB_BASE_URL.",
            **portal_context(usuario),
        ), 503

    # Com uma origem externa configurada, o Portal atua como proxy reverso e
    # mantem a URL publica do Render no navegador. O subprocesso local existe
    # apenas como compatibilidade quando a origem aponta para loopback.
    riob_target = urllib.parse.urlparse(RIOB_BASE_URL)
    if riob_target.hostname in {"127.0.0.1", "localhost", "::1"}:
        if not ensure_local_riob_app("riob"):
            return render_template(
                "app_placeholder.html",
                app_key=app_key,
                mensagem=app_startup_message("riob", "Nao foi possivel iniciar o RioB local."),
                **portal_context(usuario),
            ), 502

    route = "/" if embedded else riob_app_path(app_key, subpath)
    parsed_default = urllib.parse.urlparse(route)
    upstream_path = parsed_default.path or "/"
    upstream_query = parsed_default.query
    query = request.query_string.decode("utf-8", errors="ignore")
    if query:
        upstream_query = f"{upstream_query}&{query}" if upstream_query else query

    upstream_url = f"{RIOB_BASE_URL}{upstream_path}"
    if upstream_query:
        upstream_url += "?" + upstream_query

    headers = {}
    for key, value in request.headers.items():
        lk = key.lower()
        if lk in {"host", "connection", "content-length", "accept-encoding"}:
            continue
        headers[key] = value
    headers["X-Usuario-Id"] = str(usuario["id"])
    headers["X-Usuario-Nome"] = usuario.get("nome") or usuario.get("login") or ""
    headers["X-Usuario-Login"] = usuario["login"]
    headers["X-Usuario-Perfil"] = usuario.get("perfil") or "usuario"
    headers["X-Forwarded-Prefix"] = "/apps/riob"

    data = request.get_data() if request.method in {"POST", "PUT", "PATCH"} else None
    req = urllib.request.Request(upstream_url, data=data, headers=headers, method=request.method)

    try:
        with open_riob_request(req, timeout=120) as resp:
            body = resp.read()
            status = resp.status
            resp_headers = resp.headers
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
        resp_headers = exc.headers
    except Exception as exc:
        return render_template(
            "app_placeholder.html",
            app_key=app_key,
            mensagem=f"Nao foi possivel acessar o RioB em {RIOB_BASE_URL}: {exc}",
            **portal_context(usuario),
        ), 502

    content_type = resp_headers.get("Content-Type", "application/octet-stream")
    if "text/html" in content_type:
        body = rewrite_riob_html(body)
        if embedded:
            embedded_style = """
<style id="nanotech-riob-embedded">
  .topo,
  .menu,
  .menu-overlay,
  .nanotech-badge,
  #menuLogoutBtn {
    display: none !important;
  }
  html,
  body {
    min-height: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
  }
  html {
    overflow-x: hidden !important;
    overflow-y: scroll !important;
    scrollbar-gutter: stable;
  }
  body:not(.modal-open):not(.login-active):not(.menu-open) {
    overflow-y: auto !important;
  }
  body {
    padding-top: 12px !important;
  }
  .kanban {
    overflow-x: scroll !important;
    overflow-y: visible !important;
    padding-bottom: 16px !important;
  }
</style>
"""
            text = body.decode("utf-8", errors="replace")
            text = text.replace("</head>", embedded_style + "</head>", 1)
            body = text.encode("utf-8")
    elif "javascript" in content_type or upstream_path.endswith(".js"):
        body = rewrite_riob_javascript(body)

    response = Response(body, status=status, content_type=content_type)
    excluded = {
        "connection",
        "content-encoding",
        "content-length",
        "transfer-encoding",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "upgrade",
    }
    for key, value in resp_headers.items():
        lk = key.lower()
        if lk in excluded:
            continue
        if lk == "location":
            value = rewrite_riob_location(value)
        response.headers[key] = value
    return response


@app.route("/apps/riob", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/apps/riob/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/apps/riob/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@login_required
def riob_proxy(subpath=""):
    if request.method == "GET" and not subpath:
        usuario = current_user_or_logout()
        return render_template(
            "integrated_frame.html",
            active_page="dashboards",
            app_nome="Rio Branco",
            frame_url=url_for("riob_proxy", subpath="embed"),
            **portal_context(usuario),
        )
    if subpath == "embed":
        return riob_proxy_response("riob", "", embedded=True)
    if subpath == "original":
        return riob_proxy_response("riob", "")
    return riob_proxy_response("riob", subpath)


@app.route("/apps/<app_key>/riob", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/apps/<app_key>/riob/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/apps/<app_key>/riob/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@login_required
def riob_module_proxy(app_key, subpath=""):
    if app_key == "riob-cameras" and not subpath:
        return redirect("/apps/riob-cameras")
    if app_key in LOCAL_RIOB_APPS:
        return local_riob_proxy_response(app_key, subpath)
    if app_key in LOCAL_RIOB_ALIASES:
        target_key, fragment = LOCAL_RIOB_ALIASES[app_key]
        if subpath:
            return local_riob_proxy_response(target_key, subpath)
        return redirect(f"/apps/{target_key}{fragment}")
    if app_key not in RIOB_ROUTE_DEFAULTS:
        return jsonify({"erro": "modulo RioB nao encontrado"}), 404
    return riob_proxy_response(app_key, subpath)


@app.route("/apps/<app_key>")
@login_required
def app_placeholder(app_key):
    if app_key == "riob":
        return redirect(url_for("riob_proxy"))
    if app_key == "riob-cameras":
        usuario = current_user_or_logout()
        return render_template(
            "integrated_frame.html",
            active_page="config",
            app_nome="Câmeras RioB",
            frame_url=url_for("riob_proxy", subpath="monitor/cameras/"),
            **portal_context(usuario),
        )
    if app_key in LOCAL_RIOB_APPS:
        return local_riob_proxy_response(app_key, "")
    if app_key in LOCAL_RIOB_ALIASES:
        target_key, fragment = LOCAL_RIOB_ALIASES[app_key]
        return redirect(f"/apps/{target_key}{fragment}")
    if app_key in RIOB_ROUTE_DEFAULTS:
        return riob_proxy_response(app_key, "")
    selected = next((item for item in list_apps() if item["app_key"] == app_key), None)
    if selected and selected.get("url") and selected["url"] != request.path:
        return redirect(selected["url"])
    return render_template(
        "app_placeholder.html",
        app_key=app_key,
        **portal_context(),
    )


# ---------------------------------------------------------------------------
# Integracao do app Automacao
# ---------------------------------------------------------------------------
def tcp_open(host, port, timeout=0.5):
    import socket

    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def python_bin_for(*candidates):
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    base_venv_python = BASE_DIR / ".venv" / "bin" / "python"
    if base_venv_python.exists():
        return base_venv_python
    return Path(sys.executable)


def log_app_startup_error(app_key, exc):
    _app_startup_errors[app_key] = str(exc)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    message = f"\n[{timestamp}] Falha ao iniciar {app_key}: {exc}\n"
    try:
        with (BASE_DIR / f"{app_key}.log").open("ab") as log_file:
            log_file.write(message.encode("utf-8", errors="replace"))
    except Exception:
        pass


def mysql_database_url(database):
    user = urllib.parse.quote_plus(DB_CONFIG["user"])
    password = urllib.parse.quote_plus(DB_CONFIG["password"])
    host = DB_CONFIG["host"]
    port = DB_CONFIG["port"]
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


def configured_database_url(env, key):
    value = str(env.get(key) or "").strip()
    if value.lower() in {"", "false", "none", "null"}:
        return ""
    return value


def app_startup_message(app_key, fallback):
    detail = _app_startup_errors.get(app_key)
    log_name = f"{app_key}.log"
    if detail:
        return f"{fallback} Detalhe: {detail}. Log: {log_name}."
    if (BASE_DIR / log_name).exists():
        return f"{fallback} Log: {log_name}."
    return fallback


def ensure_automacao_app():
    """Sobe o app legado de automacao em loopback quando o usuario abre uma tela dele."""
    global _automacao_proc
    if tcp_open("127.0.0.1", AUTOMACAO_PORT):
        _app_startup_errors.pop("automacao", None)
        return True

    with _automacao_lock:
        if tcp_open("127.0.0.1", AUTOMACAO_PORT):
            _app_startup_errors.pop("automacao", None)
            return True
        if _automacao_proc is not None and _automacao_proc.poll() is None:
            time.sleep(0.5)
            ok = tcp_open("127.0.0.1", AUTOMACAO_PORT)
            if ok:
                _app_startup_errors.pop("automacao", None)
            return ok

        if not (AUTOMACAO_DIR / "app.py").exists():
            log_app_startup_error("automacao", f"codigo nao encontrado em {AUTOMACAO_DIR / 'app.py'}")
            return False

        python_bin = python_bin_for(AUTOMACAO_DIR / ".venv" / "bin" / "python")

        env = os.environ.copy()
        env.pop("WERKZEUG_SERVER_FD", None)
        env.pop("WERKZEUG_RUN_MAIN", None)
        env.update({
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(AUTOMACAO_PORT),
            "APP_DEBUG": "0",
            "DATABASE_PATH": str(AUTOMACAO_DIR / "homologacao.db"),
            "DRIVER_MONITOR_ENABLED": env.get("DRIVER_MONITOR_ENABLED", "1"),
            "PYTHONUNBUFFERED": "1",
        })
        try:
            log_file = (BASE_DIR / "automacao.log").open("ab")
            _automacao_proc = subprocess.Popen(
                [str(python_bin), "app.py"],
                cwd=str(AUTOMACAO_DIR),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            log_app_startup_error("automacao", exc)
            return False
        attempts = max(1, int(AUTOMACAO_STARTUP_WAIT / 0.25))
        for _ in range(attempts):
            if tcp_open("127.0.0.1", AUTOMACAO_PORT):
                _app_startup_errors.pop("automacao", None)
                return True
            if _automacao_proc.poll() is not None:
                log_app_startup_error(
                    "automacao",
                    f"processo encerrou antes de abrir a porta 127.0.0.1:{AUTOMACAO_PORT} "
                    f"com codigo {_automacao_proc.returncode}",
                )
                return False
            time.sleep(0.25)
        log_app_startup_error(
            "automacao",
            f"processo iniciou, mas a porta 127.0.0.1:{AUTOMACAO_PORT} nao respondeu "
            f"em {AUTOMACAO_STARTUP_WAIT:.0f}s",
        )
    return False


def rewrite_automacao_location(value, prefix="/apps/automacao"):
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme and parsed.netloc:
        if value.startswith(AUTOMACAO_BASE_URL):
            return prefix + parsed.path + (("?" + parsed.query) if parsed.query else "")
        return value
    if value.startswith(prefix):
        return value
    if value.startswith("/"):
        return prefix + value
    return value


def automacao_theme_replacements():
    theme = current_theme_key()
    if theme == "autoblue":
        return {}
    if theme == "fin-blue":
        return {
            "#003366": "#0b1020",
            "#004c99": "#111a33",
            "#b9d7f5": "#aeb7e7",
            "#a60000": "#fb7185",
            "#f4f4f4": "#0b1020",
            "background:white": "background:#111a33",
            "background: white": "background:#111a33",
            "box-shadow:0 0 5px #ccc": "box-shadow:0 12px 40px rgba(0,0,0,.35)",
            "border:1px solid #ddd": "border:1px solid rgba(255,255,255,.16)",
            "color:#555": "color:#aeb7e7",
        }
    if theme == "zapgreen":
        return {
            "#003366": "#07111f",
            "#004c99": "#128c4a",
            "#b9d7f5": "#193246",
            "#a60000": "#f87171",
            "#f4f4f4": "#07111f",
            "background:white": "background:#0d1727",
            "background: white": "background:#0d1727",
            "background-color:white": "background-color:#0d1727",
            "background-color: white": "background-color:#0d1727",
            "box-shadow:0 0 5px #ccc": "box-shadow:0 24px 80px rgba(0,0,0,.35)",
            "border:1px solid #ddd": "border:1px solid rgba(148,163,184,.18)",
            "color:#555": "color:#99a8c2",
        }
    if theme == "pacsred":
        return {
            "#003366": "#2f3742",
            "#004c99": "#8f1d2c",
            "#b9d7f5": "#fff1f2",
            "#a60000": "#c81e3a",
            "#f4f4f4": "#f7f8fb",
            "background:white": "background:#ffffff",
            "background: white": "background:#ffffff",
            "background-color:white": "background-color:#ffffff",
            "background-color: white": "background-color:#ffffff",
            "box-shadow:0 0 5px #ccc": "box-shadow:0 18px 42px rgba(143,29,44,.12)",
            "border:1px solid #ddd": "border:1px solid #e5d3d7",
            "color:#555": "color:#6b7280",
        }
    return {
        "#003366": "#ff9800",
        "#004c99": "#e68900",
        "#b9d7f5": "#fff3e0",
    }


def rewrite_automacao_html(content, prefix="/apps/automacao", apply_theme=True):
    """Ajusta links absolutos do app legado para rodarem sob o prefixo do portal."""
    text = content.decode("utf-8", errors="replace")
    replacements = {
        'href="/': f'href="{prefix}/',
        "href='/": f"href='{prefix}/",
        'src="/': f'src="{prefix}/',
        "src='/": f"src='{prefix}/",
        'action="/': f'action="{prefix}/',
        "action='/": f"action='{prefix}/",
        'fetch("/': f'fetch("{prefix}/',
        "fetch('/": f"fetch('{prefix}/",
        '"/api/': f'"{prefix}/api/',
        "'/api/": f"'{prefix}/api/",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    if apply_theme:
        for source, target in automacao_theme_replacements().items():
            text = text.replace(source, target)
    return text.encode("utf-8")


def automacao_active_page(subpath):
    path = "/" + (subpath or "")
    if path in {"/", ""} or path.startswith("/tempo-real"):
        return "dashboards"
    if path.startswith("/motores") or path.startswith("/motor") or path.startswith("/sensores/drivers"):
        return "cadastros"
    if path.startswith("/alarmes"):
        return "workflow"
    if path.startswith("/historico"):
        return "relatorios"
    if path.startswith("/setores"):
        return "config"
    return "dashboards"


def extract_automacao_page(content):
    """Extrai apenas estilo e conteudo da automacao para inserir no shell NanotechSoft."""
    text = rewrite_automacao_html(content).decode("utf-8", errors="replace")
    style_match = re.search(r"<style>(.*?)</style>", text, flags=re.I | re.S)
    style = style_match.group(1) if style_match else ""
    style = style.replace(".content", ".automacao-content")
    style = style.replace("body{", ".automacao-page{")
    if current_theme_key() == "zapgreen":
        style += """
.automacao-page,
.automacao-content {
  background: transparent !important;
  color: #e5eefc;
}
.automacao-content .card,
.automacao-content .panel,
.automacao-content table,
.automacao-content form,
.automacao-content section,
.automacao-content .status-card,
.automacao-content .sensor-card {
  background: #0d1727 !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: #e5eefc !important;
}
.automacao-content input,
.automacao-content select,
.automacao-content textarea {
  background: #07111f !important;
  border-color: rgba(148, 163, 184, 0.24) !important;
  color: #e5eefc !important;
}
.automacao-content th,
.automacao-content button,
.automacao-content .btn {
  background: #128c4a !important;
  color: #ffffff !important;
}
.automacao-content td,
.automacao-content p,
.automacao-content span,
.automacao-content label {
  color: inherit;
}
"""
    if current_theme_key() == "pacsred":
        style += """
.automacao-page,
.automacao-content {
  background: transparent !important;
  color: #2d3038;
}
.automacao-content .card,
.automacao-content .panel,
.automacao-content table,
.automacao-content form,
.automacao-content section,
.automacao-content .status-card,
.automacao-content .sensor-card {
  background: #ffffff !important;
  border-color: #e5d3d7 !important;
  color: #2d3038 !important;
}
.automacao-content input,
.automacao-content select,
.automacao-content textarea {
  background: #ffffff !important;
  border-color: #e5d3d7 !important;
  color: #2d3038 !important;
}
.automacao-content th,
.automacao-content button,
.automacao-content .btn {
  background: #8f1d2c !important;
  color: #ffffff !important;
}
.automacao-content td,
.automacao-content p,
.automacao-content span,
.automacao-content label {
  color: inherit;
}
"""

    content_match = re.search(
        r'<div class="content">\s*(.*?)\s*</div>\s*</body>',
        text,
        flags=re.I | re.S,
    )
    app_content = content_match.group(1) if content_match else text
    return style, app_content


def automacao_proxy_response(subpath="", integrated=True):
    if not ensure_automacao_app():
        return render_template(
            "app_placeholder.html",
            app_key="automacao",
            erro=app_startup_message("automacao", "Automacao nao iniciou."),
            **portal_context(),
        ), 502

    upstream_path = "/" + (subpath or "")
    query = request.query_string.decode("utf-8", errors="ignore")
    upstream_url = f"{AUTOMACAO_BASE_URL}{upstream_path}"
    if query:
        upstream_url += "?" + query

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "connection"}
    }
    data = request.get_data() if request.method in {"POST", "PUT", "PATCH"} else None
    req = urllib.request.Request(upstream_url, data=data, headers=headers, method=request.method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            response_headers = []
            for key, value in resp.headers.items():
                if key.lower() in {"content-length", "connection", "transfer-encoding", "content-encoding"}:
                    continue
                if key.lower() == "location":
                    value = rewrite_automacao_location(
                        value,
                        "/apps/automacao" if integrated else "/apps/automacao/original",
                    )
                response_headers.append((key, value))
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
        content_type = exc.headers.get("Content-Type", "")
        response_headers = []
        for key, value in exc.headers.items():
            if key.lower() in {"content-length", "connection", "transfer-encoding", "content-encoding"}:
                continue
            if key.lower() == "location":
                value = rewrite_automacao_location(
                    value,
                    "/apps/automacao" if integrated else "/apps/automacao/original",
                )
            response_headers.append((key, value))

    if "text/html" in content_type:
        if integrated:
            style, app_content = extract_automacao_page(body)
            body = render_template(
                "integrated_app.html",
                active_page=automacao_active_page(subpath),
                app_nome="Automacao",
                app_style=style,
                app_content=app_content,
                **portal_context(),
            ).encode("utf-8")
        else:
            body = rewrite_automacao_html(
                body,
                prefix="/apps/automacao/original",
                apply_theme=True,
            )
            body = apply_standalone_theme(body.decode("utf-8", errors="replace")).encode("utf-8")
        response_headers = [
            (k, v)
            for k, v in response_headers
            if k.lower() not in {"content-length", "content-type"}
        ]
        content_type = "text/html; charset=utf-8"
    return Response(body, status=status, headers=response_headers, content_type=content_type)


@app.route("/apps/automacao", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def automacao_proxy_root():
    return automacao_proxy_response("")


@app.route("/apps/automacao/original", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def automacao_original_root():
    return automacao_proxy_response("", integrated=False)


@app.route("/apps/automacao/original/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/apps/automacao/original/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def automacao_original_proxy(subpath):
    return automacao_proxy_response(subpath, integrated=False)


@app.route("/apps/automacao/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/apps/automacao/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def automacao_proxy(subpath):
    return automacao_proxy_response(subpath)


# ---------------------------------------------------------------------------
# Integracao do app NanoPonto
# ---------------------------------------------------------------------------
def ensure_nanoponto_database():
    conn = mysql.connector.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )
    cur = conn.cursor()
    cur.execute("CREATE DATABASE IF NOT EXISTS nanoponto CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    conn.commit()
    cur.close()
    conn.close()


def ensure_nanoponto_app():
    """Sobe o NanoPonto legado em loopback quando uma tela dele e aberta."""
    global _nanoponto_proc
    if tcp_open("127.0.0.1", NANOPONTO_PORT):
        _app_startup_errors.pop("nanoponto", None)
        return True

    with _nanoponto_lock:
        if tcp_open("127.0.0.1", NANOPONTO_PORT):
            _app_startup_errors.pop("nanoponto", None)
            return True
        if _nanoponto_proc is not None and _nanoponto_proc.poll() is None:
            time.sleep(0.5)
            ok = tcp_open("127.0.0.1", NANOPONTO_PORT)
            if ok:
                _app_startup_errors.pop("nanoponto", None)
            return ok

        if not (NANOPONTO_DIR / "app.py").exists():
            log_app_startup_error("nanoponto", f"codigo nao encontrado em {NANOPONTO_DIR / 'app.py'}")
            return False

        python_bin = python_bin_for(NANOPONTO_DIR / ".venv" / "bin" / "python")
        atestado_upload_dir = NANOPONTO_DIR / "data" / "atestados"
        atestado_upload_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.pop("WERKZEUG_SERVER_FD", None)
        env.pop("WERKZEUG_RUN_MAIN", None)
        database_url = configured_database_url(env, "NANOPONTO_DATABASE_URL")
        if not database_url:
            try:
                ensure_nanoponto_database()
            except Exception as exc:
                log_app_startup_error("nanoponto", exc)
                return False
            database_url = mysql_database_url("nanoponto")
        env.update({
            "FLASK_APP": "app.py",
            "FLASK_RUN_HOST": "127.0.0.1",
            "FLASK_RUN_PORT": str(NANOPONTO_PORT),
            "NANOPONTO_DATABASE_URL": database_url,
            "NANOPONTO_MYSQL_HOST": DB_CONFIG["host"],
            "NANOPONTO_MYSQL_PORT": str(DB_CONFIG["port"]),
            "NANOPONTO_MYSQL_USER": DB_CONFIG["user"],
            "NANOPONTO_MYSQL_PASSWORD": DB_CONFIG["password"],
            "NANOPONTO_MYSQL_DATABASE": "nanoponto",
            "APP_NAME": "NanoPonto",
            "SECRET_KEY": env.get("NANOPONTO_SECRET_KEY", "nanoponto-dev-key"),
            "ALLOW_SYSTEM_TIME_FALLBACK": env.get("ALLOW_SYSTEM_TIME_FALLBACK", "1"),
            "ATESTADO_UPLOAD_DIR": str(atestado_upload_dir),
        })
        try:
            log_file = (BASE_DIR / "nanoponto.log").open("ab")
            _nanoponto_proc = subprocess.Popen(
                [str(python_bin), "-m", "flask", "run", "--host", "127.0.0.1", "--port", str(NANOPONTO_PORT)],
                cwd=str(NANOPONTO_DIR),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            log_app_startup_error("nanoponto", exc)
            return False
        for _ in range(40):
            if tcp_open("127.0.0.1", NANOPONTO_PORT):
                _app_startup_errors.pop("nanoponto", None)
                return True
            time.sleep(0.25)
        log_app_startup_error("nanoponto", f"processo iniciou, mas a porta 127.0.0.1:{NANOPONTO_PORT} nao respondeu")
    return False


def nanoponto_prefix(integrated=True):
    return "/apps/nanoponto" if integrated else "/apps/nanoponto/original"


def rewrite_nanoponto_location(value, prefix):
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme and parsed.netloc:
        if value.startswith(NANOPONTO_BASE_URL):
            return prefix + parsed.path + (("?" + parsed.query) if parsed.query else "")
        return value
    if value.startswith(prefix):
        return value
    if value.startswith("/"):
        return prefix + value
    return value


def rewrite_nanoponto_html(content, integrated=True):
    prefix = nanoponto_prefix(integrated)
    text = content.decode("utf-8", errors="replace")
    replacements = {
        'href="/': f'href="{prefix}/',
        "href='/": f"href='{prefix}/",
        'src="/': f'src="{prefix}/',
        "src='/": f"src='{prefix}/",
        'action="/': f'action="{prefix}/',
        "action='/": f"action='{prefix}/",
        'fetch("/': f'fetch("{prefix}/',
        "fetch('/": f"fetch('{prefix}/",
        '"/api/': f'"{prefix}/api/',
        "'/api/": f"'{prefix}/api/",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    if integrated:
        text = text.replace("Cadastro de Funcionario", "Cadastro de Usuarios")
        text = text.replace("Salvar funcionario", "Salvar usuario")
        text = text.replace("Funcionarios cadastrados", "Usuarios cadastrados")
        text = text.replace(">Funcionarios<", ">Usuarios<")
    return apply_standalone_theme(text)


def rewrite_nanoponto_javascript(content, integrated=True):
    prefix = nanoponto_prefix(integrated)
    text = content.decode("utf-8", errors="replace")
    text = re.sub(
        r'activeAdminPanel:\s*"punch-card"',
        'activeAdminPanel: new URLSearchParams(window.location.search).get("panel") || "punch-card"',
        text,
        count=1,
    )
    text = re.sub(
        r'const APP_BASE_PATH = .*?;',
        f'const APP_BASE_PATH = "{prefix}";',
        text,
        count=1,
    )
    return text.encode("utf-8")


def rewrite_nanoponto_css(content):
    text = content.decode("utf-8", errors="replace")
    text += """

body.theme-rio_branco {
  --bg: #f4f6f9;
  --bg-deep: #edf1f5;
  --panel: rgba(255, 255, 255, 0.96);
  --panel-strong: #ff9800;
  --text: #263238;
  --muted: #667085;
  --line: #d9e1ea;
  --accent: #ff9800;
  --accent-strong: #c66900;
  --mint: #fff3e0;
  --radius: 8px;
}

body.theme-autoblue {
  --bg: #f4f8fd;
  --bg-deep: #e6f2ff;
  --panel: rgba(255, 255, 255, 0.96);
  --panel-strong: #003366;
  --text: #263238;
  --muted: #5b6f86;
  --line: #cbd7e6;
  --accent: #003366;
  --accent-strong: #004c99;
  --mint: #e6f2ff;
  --radius: 8px;
}

body.theme-fin-blue {
  --bg: #0b1020;
  --bg-deep: #111a33;
  --panel: rgba(17, 26, 51, 0.92);
  --panel-strong: #111a33;
  --text: #e8ecff;
  --muted: #aeb7e7;
  --line: rgba(255, 255, 255, 0.16);
  --accent: #5eead4;
  --accent-strong: #60a5fa;
  --mint: #132340;
  --radius: 8px;
}

body.theme-pontobege {
  --bg: #f5efe4;
  --bg-deep: #e6dccb;
  --panel: rgba(255, 252, 245, 0.92);
  --panel-strong: #183237;
  --text: #183237;
  --muted: #5f6d63;
  --line: rgba(24, 50, 55, 0.14);
  --accent: #e08b3e;
  --accent-strong: #bb5b2a;
  --mint: #8fc1a9;
  --radius: 8px;
}

body.theme-pacsred {
  --bg: #f7f8fb;
  --bg-deep: #fff1f2;
  --panel: rgba(255, 255, 255, 0.94);
  --panel-strong: #2f3742;
  --text: #2d3038;
  --muted: #6b7280;
  --line: #e5d3d7;
  --accent: #c81e3a;
  --accent-strong: #8f1d2c;
  --mint: #dbeafe;
  --radius: 8px;
}

.notech-integrated-nanoponto .shell {
  width: min(1180px, 100%);
  padding: 0;
}

.notech-integrated-nanoponto .admin-menu,
.notech-integrated-nanoponto .hero {
  display: none !important;
}

.notech-integrated-nanoponto #auth-grid {
  display: none !important;
}

.notech-integrated-nanoponto #app-shell.hidden {
  display: block !important;
}

.notech-integrated-nanoponto .grid,
.notech-integrated-nanoponto .panel {
  margin-bottom: 0;
}
"""
    return text.encode("utf-8")


def extract_nanoponto_integrated(content):
    text = rewrite_nanoponto_html(content, integrated=True)
    link_tags = "\n".join(re.findall(r'<link[^>]+rel=["\']stylesheet["\'][^>]*>', text, flags=re.I))
    style_tags = "\n".join(re.findall(r"<style[^>]*>.*?</style>", text, flags=re.I | re.S))
    body_match = re.search(r"<body[^>]*>(.*?)</body>", text, flags=re.I | re.S)
    body = body_match.group(1) if body_match else text
    content = f"""
{link_tags}
{style_tags}
<div class="nanoponto-app notech-integrated-nanoponto">
  {body}
</div>
"""
    panel = request.args.get("panel") or "punch-card"
    active_pages = {
        "punch-card": "ponto",
        "recent-punches-card": "ponto",
        "bank-card": "ponto",
        "hours-report-card": "ponto",
        "export-card": "ponto",
        "compliance-card": "ponto",
        "employee-card": "ponto",
        "calendar-card": "ponto",
        "justify-card": "workflow",
        "medical-certificate-card": "workflow",
        "agenda-card": "workflow",
        "settings-card": "config",
        "email-card": "config",
    }
    return active_pages.get(panel, "dashboards"), content


def transform_nanoponto_cookie_header(value):
    if not value:
        return value
    parts = []
    for chunk in value.split(";"):
        item = chunk.strip()
        if item.startswith("session="):
            continue
        if item.startswith("nanoponto_session="):
            item = "session=" + item.split("=", 1)[1]
        parts.append(item)
    return "; ".join(parts)


def transform_nanoponto_set_cookie(value):
    if not value:
        return value
    return value.replace("session=", "nanoponto_session=", 1)


def nanoponto_login_payload(usuario):
    if user_is_admin(usuario):
        return {
            "role": "admin",
            "username": "admin",
            "password": os.environ.get("NANOPONTO_ADMIN_PASSWORD", "4625190000100"),
        }
    return {
        "role": "employee",
        "username": os.environ.get("NANOPONTO_DEFAULT_EMPLOYEE_CPF", "06587583903"),
        "password": os.environ.get("NANOPONTO_DEFAULT_EMPLOYEE_PASSWORD", "06587583903"),
    }


def create_nanoponto_session_cookie(usuario):
    if request.cookies.get("nanoponto_session"):
        return None
    payload = json.dumps(nanoponto_login_payload(usuario)).encode("utf-8")
    req = urllib.request.Request(
        f"{NANOPONTO_BASE_URL}/api/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_cookie = resp.headers.get("Set-Cookie", "")
    except Exception:
        return None
    if not raw_cookie:
        return None
    portal_cookie = transform_nanoponto_set_cookie(raw_cookie)
    session_pair = portal_cookie.split(";", 1)[0]
    if "=" not in session_pair:
        return None
    cookie_value = session_pair.split("=", 1)[1]
    return {
        "upstream_cookie": f"session={cookie_value}",
        "set_cookie": portal_cookie,
    }


def nanoponto_proxy_response(subpath="", integrated=True):
    if not ensure_nanoponto_app():
        return render_template(
            "app_placeholder.html",
            app_key="nanoponto",
            erro=app_startup_message("nanoponto", "NanoPonto nao iniciou."),
            **portal_context(),
        ), 502

    usuario = current_user_or_logout()
    auto_session = create_nanoponto_session_cookie(usuario)
    upstream_path = "/" + (subpath or "")
    query = request.query_string.decode("utf-8", errors="ignore")
    upstream_url = f"{NANOPONTO_BASE_URL}{upstream_path}"
    if query:
        upstream_url += "?" + query

    headers = {}
    for key, value in request.headers.items():
        lowered = key.lower()
        if lowered in {"host", "content-length", "connection"}:
            continue
        if lowered == "cookie":
            value = transform_nanoponto_cookie_header(value)
            if auto_session:
                value = (value + "; " if value else "") + auto_session["upstream_cookie"]
        headers[key] = value
    if auto_session and "Cookie" not in headers and "cookie" not in {key.lower() for key in headers}:
        headers["Cookie"] = auto_session["upstream_cookie"]
    data = request.get_data() if request.method in {"POST", "PUT", "PATCH"} else None
    req = urllib.request.Request(upstream_url, data=data, headers=headers, method=request.method)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            response_headers = []
            for key, value in resp.headers.items():
                lowered = key.lower()
                if lowered in {"content-length", "connection", "transfer-encoding", "content-encoding"}:
                    continue
                if lowered == "location":
                    value = rewrite_nanoponto_location(value, nanoponto_prefix(integrated))
                if lowered == "set-cookie":
                    value = transform_nanoponto_set_cookie(value)
                response_headers.append((key, value))
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
        content_type = exc.headers.get("Content-Type", "")
        response_headers = []
        for key, value in exc.headers.items():
            lowered = key.lower()
            if lowered in {"content-length", "connection", "transfer-encoding", "content-encoding"}:
                continue
            if lowered == "location":
                value = rewrite_nanoponto_location(value, nanoponto_prefix(integrated))
            if lowered == "set-cookie":
                value = transform_nanoponto_set_cookie(value)
            response_headers.append((key, value))

    if auto_session:
        response_headers.append(("Set-Cookie", auto_session["set_cookie"]))

    if "text/html" in content_type:
        if integrated:
            active_page, app_content = extract_nanoponto_integrated(body)
            body = render_template(
                "integrated_app.html",
                active_page=active_page,
                app_nome="NanoPonto",
                app_style="",
                app_content=app_content,
                **portal_context(),
            ).encode("utf-8")
        else:
            body = rewrite_nanoponto_html(body, integrated=False).encode("utf-8")
        response_headers = [
            (k, v)
            for k, v in response_headers
            if k.lower() not in {"content-length", "content-type"}
        ]
        content_type = "text/html; charset=utf-8"
    elif "javascript" in content_type or subpath.endswith(".js"):
        body = rewrite_nanoponto_javascript(body, integrated=integrated)
        response_headers = [(k, v) for k, v in response_headers if k.lower() != "content-length"]
    elif "text/css" in content_type or subpath.endswith(".css"):
        body = rewrite_nanoponto_css(body)
        response_headers = [(k, v) for k, v in response_headers if k.lower() != "content-length"]

    return Response(body, status=status, headers=response_headers, content_type=content_type)


@app.route("/apps/nanoponto", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def nanoponto_proxy_root():
    return nanoponto_proxy_response("")


@app.route("/apps/nanoponto/original", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def nanoponto_original_root():
    return nanoponto_proxy_response("", integrated=False)


@app.route("/apps/nanoponto/original/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/apps/nanoponto/original/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def nanoponto_original_proxy(subpath):
    return nanoponto_proxy_response(subpath, integrated=False)


@app.route("/apps/nanoponto/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/apps/nanoponto/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def nanoponto_proxy(subpath):
    return nanoponto_proxy_response(subpath)


# ---------------------------------------------------------------------------
# Integracao do app Zap
# ---------------------------------------------------------------------------
def ensure_zap_database():
    conn = mysql.connector.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )
    cur = conn.cursor()
    cur.execute("CREATE DATABASE IF NOT EXISTS zap_workflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    conn.commit()
    cur.close()
    conn.close()


def zap_database_url():
    return mysql_database_url("zap_workflow")


def ensure_zap_app():
    """Sobe o Zap Workflow em loopback quando uma tela dele e aberta."""
    global _zap_proc
    if tcp_open("127.0.0.1", ZAP_PORT):
        _app_startup_errors.pop("zap", None)
        return True

    with _zap_lock:
        if tcp_open("127.0.0.1", ZAP_PORT):
            _app_startup_errors.pop("zap", None)
            return True
        if _zap_proc is not None and _zap_proc.poll() is None:
            time.sleep(0.5)
            ok = tcp_open("127.0.0.1", ZAP_PORT)
            if ok:
                _app_startup_errors.pop("zap", None)
            return ok

        if (ZAP_DIR / "zap" / "wsgi.py").exists():
            flask_app = "zap.wsgi:app"
            zap_cwd = ZAP_DIR
        elif (ZAP_DIR / "wsgi.py").exists():
            flask_app = "wsgi:app"
            zap_cwd = ZAP_DIR
        else:
            log_app_startup_error("zap", f"codigo nao encontrado em {ZAP_DIR / 'wsgi.py'}")
            return False

        python_bin = python_bin_for(ZAP_DIR / ".venv" / "bin" / "python")
        upload_folder = ZAP_DIR / "instance" / "uploads"
        upload_folder.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.pop("WERKZEUG_SERVER_FD", None)
        env.pop("WERKZEUG_RUN_MAIN", None)
        database_url = configured_database_url(env, "ZAP_DATABASE_URL")
        if not database_url:
            try:
                ensure_zap_database()
            except Exception as exc:
                log_app_startup_error("zap", exc)
                return False
            database_url = zap_database_url()
        env.update({
            "FLASK_APP": flask_app,
            "SECRET_KEY": env.get("ZAP_SECRET_KEY", "zap-dev-key"),
            "SESSION_COOKIE_NAME": "zap_session",
            "ZAP_DATABASE_URL": database_url,
            "DATABASE_URL": database_url,
            "BOOTSTRAP_ADMIN_NAME": env.get("ZAP_ADMIN_NAME", "Administrador"),
            "BOOTSTRAP_ADMIN_EMAIL": env.get("ZAP_ADMIN_EMAIL", "admin@empresa.com"),
            "BOOTSTRAP_ADMIN_PASSWORD": env.get("ZAP_ADMIN_PASSWORD", "admin"),
            "UPLOAD_FOLDER": str(upload_folder),
            "PUBLIC_BASE_URL": env.get("ZAP_PUBLIC_BASE_URL", ""),
            "GOOGLE_REDIRECT_URI": env.get(
                "ZAP_GOOGLE_REDIRECT_URI",
                f"http://127.0.0.1:{ZAP_PORT}/integrations/google/callback",
            ),
        })
        try:
            log_file = (BASE_DIR / "zap.log").open("ab")
            _zap_proc = subprocess.Popen(
                [str(python_bin), "-m", "flask", "run", "--host", "127.0.0.1", "--port", str(ZAP_PORT)],
                cwd=str(zap_cwd),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            log_app_startup_error("zap", exc)
            return False
        for _ in range(120):
            if tcp_open("127.0.0.1", ZAP_PORT):
                _app_startup_errors.pop("zap", None)
                return True
            time.sleep(0.25)
        log_app_startup_error("zap", f"processo iniciou, mas a porta 127.0.0.1:{ZAP_PORT} nao respondeu")
    return False


def zap_prefix(integrated=True):
    return "/apps/zap" if integrated else "/apps/zap/original"


def rewrite_zap_location(value, prefix):
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme and parsed.netloc:
        if value.startswith(ZAP_BASE_URL):
            return prefix + parsed.path + (("?" + parsed.query) if parsed.query else "")
        return value
    if value.startswith(prefix):
        return value
    if value.startswith("/"):
        return prefix + value
    return value


def rewrite_zap_document(content, integrated=True):
    prefix = zap_prefix(integrated)
    text = content.decode("utf-8", errors="replace")
    replacements = {
        'href="/': f'href="{prefix}/',
        "href='/": f"href='{prefix}/",
        'src="/': f'src="{prefix}/',
        "src='/": f"src='{prefix}/",
        'action="/': f'action="{prefix}/',
        "action='/": f"action='{prefix}/",
        'fetch("/': f'fetch("{prefix}/',
        "fetch('/": f"fetch('{prefix}/",
        '"/api/': f'"{prefix}/api/',
        "'/api/": f"'{prefix}/api/",
        'data-api-base=""': f'data-api-base="{prefix}"',
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return apply_standalone_theme(text)


def rewrite_zap_javascript(content, integrated=True):
    text = content.decode("utf-8", errors="replace")
    text = re.sub(
        r'const apiBase = document\.body\.dataset\.apiBase \|\| "";',
        f'const apiBase = document.body.dataset.apiBase || "{zap_prefix(integrated)}";',
        text,
        count=1,
    )
    return text.encode("utf-8")


def rewrite_zap_css(content):
    text = content.decode("utf-8", errors="replace")
    text += """

body.theme-rio_branco {
  --bg: #f4f6f9;
  --bg-2: #ffffff;
  --panel: #ffffff;
  --panel-border: #d9e1ea;
  --text: #263238;
  --muted: #667085;
  --accent: #ff9800;
  --accent-2: #c66900;
  --danger: #c62828;
  --shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
}

body.theme-autoblue {
  --bg: #f4f8fd;
  --bg-2: #e6f2ff;
  --panel: #ffffff;
  --panel-border: #cbd7e6;
  --text: #263238;
  --muted: #5b6f86;
  --accent: #003366;
  --accent-2: #004c99;
  --danger: #a60000;
  --shadow: 0 2px 8px rgba(0, 51, 102, 0.10);
}

body.theme-fin-blue {
  --bg: #0b1020;
  --bg-2: #111a33;
  --panel: rgba(17, 26, 51, 0.92);
  --panel-border: rgba(255, 255, 255, 0.16);
  --text: #e8ecff;
  --muted: #aeb7e7;
  --accent: #5eead4;
  --accent-2: #60a5fa;
  --danger: #fb7185;
  --shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
}

body.theme-pontobege {
  --bg: #f5efe4;
  --bg-2: #fffaf1;
  --panel: rgba(255, 252, 245, 0.94);
  --panel-border: rgba(24, 50, 55, 0.14);
  --text: #183237;
  --muted: #5f6d63;
  --accent: #e08b3e;
  --accent-2: #bb5b2a;
  --danger: #a60000;
  --shadow: 0 18px 40px rgba(47, 55, 45, 0.12);
}

body.theme-zapgreen {
  --bg: #07111f;
  --bg-2: #0d1727;
  --panel: rgba(14, 24, 42, 0.92);
  --panel-border: rgba(148, 163, 184, 0.18);
  --text: #e5eefc;
  --muted: #99a8c2;
  --accent: #25d366;
  --accent-2: #38bdf8;
  --danger: #f87171;
  --shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
}

body.theme-pacsred {
  --bg: #f7f8fb;
  --bg-2: #fff1f2;
  --panel: rgba(255, 255, 255, 0.94);
  --panel-border: #e5d3d7;
  --text: #2d3038;
  --muted: #6b7280;
  --accent: #c81e3a;
  --accent-2: #8f1d2c;
  --danger: #a60000;
  --shadow: 0 18px 42px rgba(143, 29, 44, 0.12);
}

.notech-integrated-zap .shell {
  display: block;
  min-height: 0;
}

.notech-integrated-zap .sidebar {
  display: none !important;
}

.notech-integrated-zap .main {
  padding: 20px;
}

.notech-integrated-zap .hero h1,
.notech-integrated-zap .page-head h1 {
  font-size: 28px;
  line-height: 1.12;
}

.notech-integrated-zap .hero,
.notech-integrated-zap .page-head {
  align-items: center;
}
"""
    return text.encode("utf-8")


def extract_zap_integrated(content, subpath):
    text = rewrite_zap_document(content, integrated=True)
    link_tags = "\n".join(re.findall(r'<link[^>]+rel=["\']stylesheet["\'][^>]*>', text, flags=re.I))
    style_tags = "\n".join(re.findall(r"<style[^>]*>.*?</style>", text, flags=re.I | re.S))
    body_match = re.search(r"<body([^>]*)>(.*?)</body>", text, flags=re.I | re.S)
    body_attrs = body_match.group(1) if body_match else ""
    body = body_match.group(2) if body_match else text
    body = re.sub(r'<audio\b.*?</audio>', "", body, flags=re.I | re.S)
    app_content = f"""
{link_tags}
{style_tags}
<div class="zap-app notech-integrated-zap" {body_attrs}>
  {body}
</div>
"""
    path = "/" + (subpath or "")
    if path.startswith("/settings"):
        active_page = "config"
    elif path.startswith("/calendar") or path.startswith("/agenda"):
        active_page = "cadastros"
    elif path.startswith("/docs"):
        active_page = "config"
    else:
        active_page = "workflow"
    return active_page, app_content


def transform_zap_cookie_header(value):
    if not value:
        return value
    parts = []
    for chunk in value.split(";"):
        item = chunk.strip()
        if item.startswith("session="):
            continue
        parts.append(item)
    return "; ".join(parts)


def transform_zap_set_cookie(value):
    if not value:
        return value
    if value.startswith("session="):
        return value.replace("session=", "zap_session=", 1)
    return value


def create_zap_session_cookie(usuario):
    if request.cookies.get("zap_session"):
        return None
    payload = urllib.parse.urlencode({
        "email": os.environ.get("ZAP_ADMIN_EMAIL", "admin@empresa.com"),
        "password": os.environ.get("ZAP_ADMIN_PASSWORD", "admin"),
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{ZAP_BASE_URL}/login",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(req, timeout=20) as resp:
            raw_cookie = resp.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as exc:
        if exc.code not in {301, 302, 303, 307, 308}:
            return None
        raw_cookie = exc.headers.get("Set-Cookie", "")
    except Exception:
        return None
    if not raw_cookie:
        return None
    portal_cookie = transform_zap_set_cookie(raw_cookie)
    session_pair = portal_cookie.split(";", 1)[0]
    if "=" not in session_pair:
        return None
    cookie_value = session_pair.split("=", 1)[1]
    return {
        "upstream_cookie": f"zap_session={cookie_value}",
        "set_cookie": portal_cookie,
    }


def zap_proxy_response(subpath="", integrated=True, require_portal_login=True):
    if not ensure_zap_app():
        if not require_portal_login:
            return Response(app_startup_message("zap", "Zap nao iniciou."), status=502, content_type="text/plain; charset=utf-8")
        return render_template(
            "app_placeholder.html",
            app_key="zap",
            erro=app_startup_message("zap", "Zap nao iniciou."),
            **portal_context(),
        ), 502

    usuario = current_user_or_logout() if require_portal_login else None
    auto_session = create_zap_session_cookie(usuario) if require_portal_login else None
    upstream_path = "/" + (subpath or "")
    query = request.query_string.decode("utf-8", errors="ignore")
    upstream_url = f"{ZAP_BASE_URL}{upstream_path}"
    if query:
        upstream_url += "?" + query

    headers = {}
    for key, value in request.headers.items():
        lowered = key.lower()
        if lowered in {"host", "content-length", "connection"}:
            continue
        if lowered == "cookie":
            value = transform_zap_cookie_header(value)
            if auto_session:
                value = (value + "; " if value else "") + auto_session["upstream_cookie"]
        headers[key] = value
    if auto_session and "cookie" not in {key.lower() for key in headers}:
        headers["Cookie"] = auto_session["upstream_cookie"]

    data = request.get_data() if request.method in {"POST", "PUT", "PATCH", "DELETE"} else None
    req = urllib.request.Request(upstream_url, data=data, headers=headers, method=request.method)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            response_headers = []
            for key, value in resp.headers.items():
                lowered = key.lower()
                if lowered in {"content-length", "connection", "transfer-encoding", "content-encoding"}:
                    continue
                if lowered == "location":
                    value = rewrite_zap_location(value, zap_prefix(integrated))
                if lowered == "set-cookie":
                    value = transform_zap_set_cookie(value)
                response_headers.append((key, value))
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
        content_type = exc.headers.get("Content-Type", "")
        response_headers = []
        for key, value in exc.headers.items():
            lowered = key.lower()
            if lowered in {"content-length", "connection", "transfer-encoding", "content-encoding"}:
                continue
            if lowered == "location":
                value = rewrite_zap_location(value, zap_prefix(integrated))
            if lowered == "set-cookie":
                value = transform_zap_set_cookie(value)
            response_headers.append((key, value))

    if auto_session:
        response_headers.append(("Set-Cookie", auto_session["set_cookie"]))

    if "text/html" in content_type:
        if not require_portal_login:
            response_headers = [(k, v) for k, v in response_headers if k.lower() != "content-length"]
        elif integrated:
            active_page, app_content = extract_zap_integrated(body, subpath)
            body = render_template(
                "integrated_app.html",
                active_page=active_page,
                app_nome="Zap",
                app_style="",
                app_content=app_content,
                **portal_context(usuario),
            ).encode("utf-8")
        else:
            body = rewrite_zap_document(body, integrated=False).encode("utf-8")
        response_headers = [(k, v) for k, v in response_headers if k.lower() not in {"content-length", "content-type"}]
        content_type = "text/html; charset=utf-8"
    elif "javascript" in content_type or subpath.endswith(".js"):
        body = rewrite_zap_javascript(body, integrated=integrated)
        response_headers = [(k, v) for k, v in response_headers if k.lower() != "content-length"]
    elif "text/css" in content_type or subpath.endswith(".css"):
        body = rewrite_zap_css(body)
        response_headers = [(k, v) for k, v in response_headers if k.lower() != "content-length"]

    return Response(body, status=status, headers=response_headers, content_type=content_type)


@app.route("/apps/zap/webhooks/whatsapp", methods=["GET", "POST"])
def zap_public_webhook_proxy():
    return zap_proxy_response("webhooks/whatsapp", require_portal_login=False)


@app.route("/apps/zap/public/uploads/<path:subpath>", methods=["GET"])
def zap_public_uploads_proxy(subpath):
    return zap_proxy_response(f"public/uploads/{subpath}", require_portal_login=False)


@app.route("/apps/zap", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def zap_proxy_root():
    return zap_proxy_response("")


@app.route("/apps/zap/original", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def zap_original_root():
    return zap_proxy_response("", integrated=False)


@app.route("/apps/zap/original/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/apps/zap/original/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def zap_original_proxy(subpath):
    return zap_proxy_response(subpath, integrated=False)


@app.route("/apps/zap/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/apps/zap/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def zap_proxy(subpath):
    return zap_proxy_response(subpath)


# ---------------------------------------------------------------------------
# Integracao do app NanoStore
# ---------------------------------------------------------------------------
def ensure_nanostore_database():
    conn = mysql.connector.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )
    cur = conn.cursor()
    cur.execute("CREATE DATABASE IF NOT EXISTS nanostore CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    conn.commit()
    cur.close()
    conn.close()


def nanostore_database_url():
    return mysql_database_url("nanostore")


def ensure_nanostore_app():
    """Sobe o NanoStore em loopback quando uma tela dele e aberta."""
    global _nanostore_proc
    if tcp_open("127.0.0.1", NANOSTORE_PORT):
        _app_startup_errors.pop("nanostore", None)
        return True

    with _nanostore_lock:
        if tcp_open("127.0.0.1", NANOSTORE_PORT):
            _app_startup_errors.pop("nanostore", None)
            return True
        if _nanostore_proc is not None and _nanostore_proc.poll() is None:
            time.sleep(0.5)
            ok = tcp_open("127.0.0.1", NANOSTORE_PORT)
            if ok:
                _app_startup_errors.pop("nanostore", None)
            return ok

        if not (NANOSTORE_DIR / "wsgi.py").exists():
            log_app_startup_error("nanostore", f"codigo nao encontrado em {NANOSTORE_DIR / 'wsgi.py'}")
            return False

        python_bin = python_bin_for(NANOSTORE_DIR / ".venv" / "bin" / "python")
        env = os.environ.copy()
        env.pop("WERKZEUG_SERVER_FD", None)
        env.pop("WERKZEUG_RUN_MAIN", None)
        database_url = configured_database_url(env, "NANOSTORE_DATABASE_URL")
        if not database_url:
            try:
                ensure_nanostore_database()
            except Exception as exc:
                log_app_startup_error("nanostore", exc)
                return False
            database_url = nanostore_database_url()
        env.update({
            "FLASK_APP": "wsgi:app",
            "SECRET_KEY": env.get("NANOSTORE_SECRET_KEY", "nanostore-dev-key"),
            "NANOSTORE_DATABASE_URL": database_url,
            "DATABASE_URL": database_url,
            "HOST": "127.0.0.1",
            "PORT": str(NANOSTORE_PORT),
            "FLASK_DEBUG": "false",
            "APP_CERT_DIR": str(NANOSTORE_DIR / "certs"),
            "PUBLIC_BASE_URL": env.get("NANOSTORE_PUBLIC_BASE_URL", ""),
            "ENABLE_HTTPS": env.get("NANOSTORE_ENABLE_HTTPS", "1"),
            "HTTP_PORT": env.get("NANOSTORE_HTTP_PORT", "5600"),
            "HTTPS_PORT": env.get("NANOSTORE_HTTPS_PORT", "443"),
            "CERT_APP_HOSTS": env.get("NANOSTORE_CERT_APP_HOSTS", ""),
            "APP_CA_CERT_PATH": env.get("NANOSTORE_CA_CERT_PATH", ""),
            "APP_HTTPS_CERT_PATH": env.get("NANOSTORE_HTTPS_CERT_PATH", ""),
        })
        try:
            log_file = (BASE_DIR / "nanostore.log").open("ab")
            _nanostore_proc = subprocess.Popen(
                [str(python_bin), "-m", "flask", "run", "--host", "127.0.0.1", "--port", str(NANOSTORE_PORT)],
                cwd=str(NANOSTORE_DIR),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            log_app_startup_error("nanostore", exc)
            return False
        for _ in range(240):
            if tcp_open("127.0.0.1", NANOSTORE_PORT):
                _app_startup_errors.pop("nanostore", None)
                return True
            time.sleep(0.25)
        log_app_startup_error("nanostore", f"processo iniciou, mas a porta 127.0.0.1:{NANOSTORE_PORT} nao respondeu")
    return False


def rewrite_nanostore_location(value, prefix):
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme and parsed.netloc:
        if value.startswith(NANOSTORE_BASE_URL):
            return prefix + parsed.path + (("?" + parsed.query) if parsed.query else "")
        return value
    if value.startswith(prefix):
        return value
    if value.startswith("/"):
        return prefix + value
    return value


def nanostore_navigation_bridge():
    return """
<script>
(function() {
  var aliases = {
    dashboard: "inicio",
    inicio: "inicio",
    workflow: "workflow",
    cadastros: "cadastros",
    compras: "lancamentos",
    financeiro: "lancamentos",
    lancamentos: "lancamentos",
    relatorios: "relatorios",
    config: "configuracao",
    configuracao: "configuracao"
  };

  function activateFromHash() {
    var raw = (window.location.hash || "").replace(/^#/, "");
    if (!raw) return;
    var key = raw.split(":")[0];
    var target = aliases[key] || key;
    var button = document.querySelector('.menu-link[data-target="' + target + '"]');
    if (button) button.click();
  }

  window.addEventListener("load", function() { setTimeout(activateFromHash, 80); });
  window.addEventListener("hashchange", activateFromHash);
})();
</script>
"""


def rewrite_nanostore_html(content, integrated=True):
    prefix = "/apps/nanostore" if integrated else "/apps/nanostore/original"
    text = content.decode("utf-8", errors="replace")
    replacements = {
        'href="/': f'href="{prefix}/',
        "href='/": f"href='{prefix}/",
        'src="/': f'src="{prefix}/',
        "src='/": f"src='{prefix}/",
        'action="/': f'action="{prefix}/',
        "action='/": f"action='{prefix}/",
        'fetch("/': f'fetch("{prefix}/',
        "fetch('/": f"fetch('{prefix}/",
        'data-api="/': f'data-api="{prefix}/',
        'data-source="/': f'data-source="{prefix}/',
        'postJson("/': f'postJson("{prefix}/',
        "`/api/": f"`{prefix}/api/",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = inject_before_body_close(text, nanostore_navigation_bridge())
    return apply_standalone_theme(text)


def rewrite_nanostore_css(content):
    text = content.decode("utf-8", errors="replace")
    text += """

body[class*="theme-"] {
  background: var(--bg, #f4f6f9);
  color: var(--text, inherit);
}

.notech-integrated-nanostore .shell {
  display: block;
  min-height: 0;
}

.notech-integrated-nanostore .sidebar {
  display: none !important;
}

.notech-integrated-nanostore .page {
  padding: 20px;
}
"""
    return text.encode("utf-8")


def extract_nanostore_integrated(content):
    text = rewrite_nanostore_html(content, integrated=True)
    link_tags = "\n".join(re.findall(r'<link[^>]+rel=["\']stylesheet["\'][^>]*>', text, flags=re.I))
    style_tags = "\n".join(re.findall(r"<style[^>]*>.*?</style>", text, flags=re.I | re.S))
    body_match = re.search(r"<body([^>]*)>(.*?)</body>", text, flags=re.I | re.S)
    body_attrs = body_match.group(1) if body_match else ""
    body = body_match.group(2) if body_match else text
    app_content = f"""
{link_tags}
{style_tags}
<div class="nanostore-app notech-integrated-nanostore" {body_attrs}>
  {body}
</div>
"""
    return "dashboards", app_content


def nanostore_proxy_response(subpath="", integrated=True):
    if not ensure_nanostore_app():
        return render_template(
            "app_placeholder.html",
            app_key="nanostore",
            erro=app_startup_message("nanostore", "NanoStore nao iniciou."),
            **portal_context(),
        ), 502

    upstream_path = "/" + (subpath or "")
    query = request.query_string.decode("utf-8", errors="ignore")
    upstream_url = f"{NANOSTORE_BASE_URL}{upstream_path}"
    if query:
        upstream_url += "?" + query

    usuario = current_user_or_logout()
    headers = {key: value for key, value in request.headers.items() if key.lower() not in {"host", "content-length", "connection"}}
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-Proto"] = request.headers.get("X-Forwarded-Proto", request.scheme)
    headers["X-Forwarded-Prefix"] = "/apps/nanostore" if integrated else "/apps/nanostore/original"
    headers["X-Portal-Usuario-Id"] = str((usuario or {}).get("id") or "")
    headers["X-Portal-Usuario-Login"] = str((usuario or {}).get("login") or "")
    headers["X-Portal-Usuario-Perfil"] = str((usuario or {}).get("perfil") or "usuario")
    headers["X-NanoStore-Perfil"] = str((usuario or {}).get("nanostore_perfil") or "")
    data = request.get_data() if request.method in {"POST", "PUT", "PATCH", "DELETE"} else None
    req = urllib.request.Request(upstream_url, data=data, headers=headers, method=request.method)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            response_headers = []
            for key, value in resp.headers.items():
                lowered = key.lower()
                if lowered in {"content-length", "connection", "transfer-encoding", "content-encoding"}:
                    continue
                if lowered == "location":
                    value = rewrite_nanostore_location(value, "/apps/nanostore" if integrated else "/apps/nanostore/original")
                response_headers.append((key, value))
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
        content_type = exc.headers.get("Content-Type", "")
        response_headers = []
        for key, value in exc.headers.items():
            lowered = key.lower()
            if lowered in {"content-length", "connection", "transfer-encoding", "content-encoding"}:
                continue
            if lowered == "location":
                value = rewrite_nanostore_location(value, "/apps/nanostore" if integrated else "/apps/nanostore/original")
            response_headers.append((key, value))

    if "text/html" in content_type:
        if integrated:
            active_page, app_content = extract_nanostore_integrated(body)
            body = render_template(
                "integrated_app.html",
                active_page=active_page,
                app_nome="NanoStore",
                app_style="",
                app_content=app_content,
                **portal_context(),
            ).encode("utf-8")
        else:
            body = rewrite_nanostore_html(body, integrated=False).encode("utf-8")
        response_headers = [(k, v) for k, v in response_headers if k.lower() not in {"content-length", "content-type"}]
        content_type = "text/html; charset=utf-8"
    elif "text/css" in content_type or subpath.endswith(".css"):
        body = rewrite_nanostore_css(body)
        response_headers = [(k, v) for k, v in response_headers if k.lower() != "content-length"]

    return Response(body, status=status, headers=response_headers, content_type=content_type)


@app.route("/apps/nanostore", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def nanostore_proxy_root():
    return nanostore_proxy_response("")


@app.route("/apps/nanostore/original", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def nanostore_original_root():
    return nanostore_proxy_response("", integrated=False)


@app.route("/apps/nanostore/original/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/apps/nanostore/original/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def nanostore_original_proxy(subpath):
    return nanostore_proxy_response(subpath, integrated=False)


@app.route("/apps/nanostore/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/apps/nanostore/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@login_required
def nanostore_proxy(subpath):
    return nanostore_proxy_response(subpath)


# ---------------------------------------------------------------------------
# Integracao do app RaioxPacs
# ---------------------------------------------------------------------------
def prefixed_raioxpacs_env(env, key):
    value = str(env.get(f"RAIOXPACS_{key}") or "").strip()
    if value:
        env[key] = value


def ensure_raioxpacs_app():
    """Sobe o RaioxPacs em loopback quando uma tela dele e aberta."""
    global _raioxpacs_proc
    if tcp_open("127.0.0.1", RAIOXPACS_PORT):
        _app_startup_errors.pop("pacs", None)
        return True

    with _raioxpacs_lock:
        if tcp_open("127.0.0.1", RAIOXPACS_PORT):
            _app_startup_errors.pop("pacs", None)
            return True
        if _raioxpacs_proc is not None and _raioxpacs_proc.poll() is None:
            time.sleep(0.5)
            ok = tcp_open("127.0.0.1", RAIOXPACS_PORT)
            if ok:
                _app_startup_errors.pop("pacs", None)
            return ok

        if not (RAIOXPACS_DIR / "app.py").exists():
            log_app_startup_error("pacs", f"codigo nao encontrado em {RAIOXPACS_DIR / 'app.py'}")
            return False

        python_bin = python_bin_for(RAIOXPACS_DIR / ".venv" / "bin" / "python")
        runtime_root = RAIOXPACS_DIR / "runtime"
        imagebox_root = Path(os.environ.get("RAIOXPACS_IMAGEBOX_PATH", str(runtime_root / "imagebox")))
        runtime_root.mkdir(parents=True, exist_ok=True)
        imagebox_root.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.pop("WERKZEUG_SERVER_FD", None)
        env.pop("WERKZEUG_RUN_MAIN", None)
        for key in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGSSLMODE"):
            prefixed_raioxpacs_env(env, key)
        database_url = (
            configured_database_url(env, "RAIOXPACS_DATABASE_URL")
            or configured_database_url(env, "PACS_DATABASE_URL")
        )
        if database_url:
            env["DATABASE_URL"] = database_url
        if env.get("RAIOXPACS_AUTO_BOOTSTRAP_SCHEMA"):
            env["AUTO_BOOTSTRAP_SCHEMA"] = env["RAIOXPACS_AUTO_BOOTSTRAP_SCHEMA"]
        env.update({
            "FLASK_APP": "app.py",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(RAIOXPACS_PORT),
            "PORT": str(RAIOXPACS_PORT),
            "APP_DEBUG": "0",
            "APP_SECRET_KEY": env.get("RAIOXPACS_SECRET_KEY", env.get("APP_SECRET_KEY", "raioxpacs-dev-key")),
            "RUNTIME_ROOT": str(runtime_root),
            "PACS_IMAGEBOX_PATH": str(imagebox_root),
            "PACS_WEB_URL": env.get("RAIOXPACS_PUBLIC_BASE_URL", env.get("PACS_WEB_URL", RAIOXPACS_BASE_URL)),
            "PYTHONUNBUFFERED": "1",
        })
        try:
            log_file = (BASE_DIR / "pacs.log").open("ab")
            _raioxpacs_proc = subprocess.Popen(
                [str(python_bin), "-m", "flask", "run", "--host", "127.0.0.1", "--port", str(RAIOXPACS_PORT)],
                cwd=str(RAIOXPACS_DIR),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            log_app_startup_error("pacs", exc)
            return False
        attempts = max(1, int(RAIOXPACS_STARTUP_WAIT / 0.25))
        for _ in range(attempts):
            if tcp_open("127.0.0.1", RAIOXPACS_PORT):
                _app_startup_errors.pop("pacs", None)
                return True
            if _raioxpacs_proc.poll() is not None:
                log_app_startup_error(
                    "pacs",
                    f"processo encerrou antes de abrir a porta 127.0.0.1:{RAIOXPACS_PORT} "
                    f"com codigo {_raioxpacs_proc.returncode}",
                )
                return False
            time.sleep(0.25)
        log_app_startup_error("pacs", f"processo iniciou, mas a porta 127.0.0.1:{RAIOXPACS_PORT} nao respondeu")
    return False


def raioxpacs_prefix(integrated=True):
    return "/apps/pacs" if integrated else "/apps/pacs/original"


def rewrite_raioxpacs_location(value, prefix):
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme and parsed.netloc:
        if value.startswith(RAIOXPACS_BASE_URL):
            return prefix + parsed.path + (("?" + parsed.query) if parsed.query else "")
        return value
    if value.startswith(prefix):
        return value
    if value.startswith("/"):
        return prefix + value
    return value


def rewrite_raioxpacs_text(text, integrated=True):
    prefix = raioxpacs_prefix(integrated)
    text = text.lstrip("\ufeff")
    replacements = {
        'href="/': f'href="{prefix}/',
        "href='/": f"href='{prefix}/",
        'src="/': f'src="{prefix}/',
        "src='/": f"src='{prefix}/",
        'action="/': f'action="{prefix}/',
        "action='/": f"action='{prefix}/",
        'fetch("/': f'fetch("{prefix}/',
        "fetch('/": f"fetch('{prefix}/",
        "fetch(`/": f"fetch(`{prefix}/",
        'api("/': f'api("{prefix}/',
        "api('/": f"api('{prefix}/",
        "api(`/": f"api(`{prefix}/",
        'window.open("/': f'window.open("{prefix}/',
        "window.open('/": f"window.open('{prefix}/",
        "window.open(`/": f"window.open(`{prefix}/",
        'window.location.href = "/': f'window.location.href = "{prefix}/',
        "window.location.href = '/": f"window.location.href = '{prefix}/",
        "window.location.href = `/": f"window.location.href = `{prefix}/",
        '"/api/': f'"{prefix}/api/',
        "'/api/": f"'{prefix}/api/",
        "`/api/": f"`{prefix}/api/",
        '"/media/': f'"{prefix}/media/',
        "'/media/": f"'{prefix}/media/",
        "`/media/": f"`{prefix}/media/",
        '"/viewer/': f'"{prefix}/viewer/',
        "'/viewer/": f"'{prefix}/viewer/",
        "`/viewer/": f"`{prefix}/viewer/",
        '"/share/': f'"{prefix}/share/',
        "'/share/": f"'{prefix}/share/",
        "`/share/": f"`{prefix}/share/",
        '"/docs/': f'"{prefix}/docs/',
        "'/docs/": f"'{prefix}/docs/",
        "`/docs/": f"`{prefix}/docs/",
        '"/reports/': f'"{prefix}/reports/',
        "'/reports/": f"'{prefix}/reports/",
        "`/reports/": f"`{prefix}/reports/",
        '"/exam-orders/': f'"{prefix}/exam-orders/',
        "'/exam-orders/": f"'{prefix}/exam-orders/",
        "`/exam-orders/": f"`{prefix}/exam-orders/",
        '"/camera-streams/': f'"{prefix}/camera-streams/',
        "'/camera-streams/": f"'{prefix}/camera-streams/",
        "`/camera-streams/": f"`{prefix}/camera-streams/",
        f'"{RAIOXPACS_BASE_URL}/': f'"{prefix}/',
        f"'{RAIOXPACS_BASE_URL}/": f"'{prefix}/",
        f"`{RAIOXPACS_BASE_URL}/": f"`{prefix}/",
        "${window.location.origin}/share/": f"${{window.location.origin}}{prefix}/share/",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def raioxpacs_navigation_bridge():
    return """
<script>
(function() {
  function applyPortalTarget() {
    var params = new URLSearchParams(window.location.search || "");
    var section = params.get("section") || (window.location.hash || "").replace(/^#/, "");
    var configTab = params.get("configTab");
    if (configTab && typeof window.setConfigTab === "function") {
      window.setConfigTab(configTab);
    }
    if (section && typeof window.setActiveSection === "function") {
      window.setActiveSection(section);
    }
  }
  window.addEventListener("load", function() { window.setTimeout(applyPortalTarget, 120); });
  window.setTimeout(applyPortalTarget, 180);
})();
</script>
"""


def raioxpacs_theme_bridge():
    theme = current_theme_key()
    palettes = {
        "rio_branco": ("#f4f6f9", "#ffffff", "#fff8ed", "#263238", "#667085", "#ff9800", "#c66900", "#d9e1ea"),
        "autoblue": ("#f4f8fd", "#ffffff", "#eef6ff", "#263238", "#5b6f86", "#003366", "#004c99", "#cbd7e6"),
        "fin-blue": ("#0b1020", "#111a33", "#0f1730", "#e8ecff", "#aeb7e7", "#5eead4", "#60a5fa", "rgba(255,255,255,.16)"),
        "pontobege": ("#f5efe4", "#fffaf1", "#f7dfc8", "#183237", "#5f6d63", "#e08b3e", "#bb5b2a", "rgba(24,50,55,.14)"),
        "zapgreen": ("#07111f", "#0d1727", "#13263a", "#e5eefc", "#99a8c2", "#25d366", "#128c4a", "rgba(148,163,184,.18)"),
        "pacsred": ("#f6f7f9", "#ffffff", "#fff1f2", "#2d3038", "#6b7280", "#c81e3a", "#8f1d2c", "#e5d3d7"),
    }
    bg, surface, alt, ink, muted, accent, strong, line = palettes.get(theme, palettes["rio_branco"])
    return f"""
<style id="nanotechsoft-pacs-global-theme">
body.theme-{theme} {{ --bg:{bg}; --surface:{surface}; --surface-alt:{alt}; --ink:{ink}; --text:{ink}; --muted:{muted}; --accent:{accent}; --accent-strong:{strong}; --line:{line}; --line-strong:{line}; background:{bg}!important; color:{ink}!important; }}
body.theme-{theme} .sidebar, body.theme-{theme} .login-hero {{ background:linear-gradient(160deg,{strong},{accent})!important; }}
body.theme-{theme} .panel, body.theme-{theme} .card, body.theme-{theme} .login-card, body.theme-{theme} .topbar, body.theme-{theme} .viewer-frame, body.theme-{theme} .viewer-empty, body.theme-{theme} table, body.theme-{theme} dialog {{ background:{surface}!important; color:{ink}!important; border-color:{line}!important; }}
body.theme-{theme} input, body.theme-{theme} select, body.theme-{theme} textarea {{ background:{surface}!important; color:{ink}!important; border-color:{line}!important; }}
</style>
"""


def rewrite_raioxpacs_body(body, content_type, subpath="", integrated=True):
    lowered = (content_type or "").lower()
    is_text = (
        "text/" in lowered
        or "javascript" in lowered
        or "json" in lowered
        or subpath.endswith((".js", ".css", ".html", ".htm", ".json"))
    )
    if not is_text:
        return body
    text = body.decode("utf-8", errors="replace")
    text = rewrite_raioxpacs_text(text, integrated=integrated)
    if "text/html" in lowered or subpath.endswith((".html", ".htm")):
        theme = current_theme_key()
        text = re.sub(
            r'(<body\b[^>]*\bclass=["\'])([^"\']*)(["\'])',
            lambda match: f"{match.group(1)}{match.group(2)} theme-{theme}{match.group(3)}",
            text, count=1, flags=re.I,
        )
        if not re.search(r'<body\b[^>]*\bclass=', text, flags=re.I):
            text = re.sub(r'<body\b', f'<body class="theme-{theme}"', text, count=1, flags=re.I)
        text = re.sub(r'</head>', raioxpacs_theme_bridge() + '</head>', text, count=1, flags=re.I)
        text = inject_before_body_close(text, raioxpacs_navigation_bridge())
    return text.encode("utf-8")


def transform_raioxpacs_cookie_header(value):
    if not value:
        return value
    parts = []
    for chunk in value.split(";"):
        item = chunk.strip()
        if item.startswith("session="):
            continue
        if item.startswith("raioxpacs_session="):
            item = "session=" + item.split("=", 1)[1]
        parts.append(item)
    return "; ".join(parts)


def transform_raioxpacs_set_cookie(value):
    if not value:
        return value
    cookie = value
    if cookie.startswith("session="):
        cookie = cookie.replace("session=", "raioxpacs_session=", 1)
    cookie = re.sub(r";\s*Path=/($|;)", r"; Path=/apps/pacs\1", cookie, count=1, flags=re.I)
    if not re.search(r";\s*Path=", cookie, flags=re.I):
        cookie += "; Path=/apps/pacs"
    return cookie


def raioxpacs_unavailable(message):
    if not session.get("usuario_id"):
        return Response(message, status=502, content_type="text/plain; charset=utf-8")
    return render_template(
        "app_placeholder.html",
        app_key="pacs",
        erro=message,
        **portal_context(),
    ), 502


def raioxpacs_proxy_response(subpath="", integrated=True):
    if not ensure_raioxpacs_app():
        return raioxpacs_unavailable(app_startup_message("pacs", "RaioxPacs nao iniciou."))

    upstream_path = "/" + (subpath or "")
    query = request.query_string.decode("utf-8", errors="ignore")
    upstream_url = f"{RAIOXPACS_BASE_URL}{upstream_path}"
    if query:
        upstream_url += "?" + query

    headers = {}
    for key, value in request.headers.items():
        lowered = key.lower()
        if lowered in {"host", "content-length", "connection"}:
            continue
        if lowered == "cookie":
            value = transform_raioxpacs_cookie_header(value)
        headers[key] = value
    portal_user = None
    if session.get("usuario_id"):
        try:
            portal_user = get_user_by_id(int(session["usuario_id"]))
        except Exception:
            portal_user = None
    headers["X-Portal-Usuario-Id"] = str((portal_user or {}).get("id") or "")
    headers["X-Portal-Usuario-Login"] = str((portal_user or {}).get("login") or "visitante")
    headers["X-Portal-Usuario-Perfil"] = str((portal_user or {}).get("perfil") or "visitante")
    data = request.get_data() if request.method in {"POST", "PUT", "PATCH", "DELETE"} else None
    req = urllib.request.Request(upstream_url, data=data, headers=headers, method=request.method)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=90) as resp:
            body = resp.read()
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            upstream_headers = resp.headers
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
        content_type = exc.headers.get("Content-Type", "")
        upstream_headers = exc.headers
    except Exception as exc:
        return raioxpacs_unavailable(f"Nao foi possivel acessar o RaioxPacs em {RAIOXPACS_BASE_URL}: {exc}")

    prefix = raioxpacs_prefix(integrated)
    response_headers = []
    excluded = {"content-length", "connection", "transfer-encoding", "content-encoding"}
    for key in upstream_headers.keys():
        values = upstream_headers.get_all(key) if hasattr(upstream_headers, "get_all") else [upstream_headers.get(key)]
        for value in values:
            if value is None:
                continue
            lowered = key.lower()
            if lowered in excluded:
                continue
            if lowered == "location":
                value = rewrite_raioxpacs_location(value, prefix)
            if lowered == "set-cookie":
                value = transform_raioxpacs_set_cookie(value)
            response_headers.append((key, value))

    body = rewrite_raioxpacs_body(body, content_type, subpath=subpath, integrated=integrated)
    if (content_type or "").lower().startswith("text/") or "javascript" in (content_type or "").lower() or "json" in (content_type or "").lower():
        response_headers = [(k, v) for k, v in response_headers if k.lower() != "content-length"]

    return Response(body, status=status, headers=response_headers, content_type=content_type)


@app.route("/apps/pacs/static/<path:subpath>", methods=["GET"])
def raioxpacs_public_static(subpath):
    return raioxpacs_proxy_response(f"static/{subpath}")


@app.route("/apps/pacs/share/<path:subpath>", methods=["GET", "POST"])
def raioxpacs_public_share(subpath):
    return raioxpacs_proxy_response(f"share/{subpath}")


@app.route("/apps/pacs/api/share/<path:subpath>", methods=["GET", "POST"])
def raioxpacs_public_share_api(subpath):
    return raioxpacs_proxy_response(f"api/share/{subpath}")


@app.route("/apps/pacs", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def raioxpacs_proxy_root():
    return raioxpacs_proxy_response("")


@app.route("/apps/pacs/original", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def raioxpacs_original_root():
    return raioxpacs_proxy_response("", integrated=False)


@app.route("/apps/pacs/original/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/apps/pacs/original/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def raioxpacs_original_proxy(subpath):
    return raioxpacs_proxy_response(subpath, integrated=False)


@app.route("/apps/pacs/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/apps/pacs/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def raioxpacs_proxy(subpath):
    return raioxpacs_proxy_response(subpath)


# ---------------------------------------------------------------------------
# Integracao de apps estaticos Nanotech
# ---------------------------------------------------------------------------
STATIC_APP_DIRS = {
    "gpsmusical": GPSMUSICAL_DIR,
    "bpa": BPA_DIR,
    "tatoo": TATOO_DIR,
    "tecnologia": TECNOLOGIA_DIR,
}

STATIC_APP_INDEX = {
    "gpsmusical": "index.html",
    "bpa": "index.html",
    "tatoo": "index.html",
    "tecnologia": "index.html",
}

STATIC_APP_NAMES = {
    "gpsmusical": "GPS Musical",
    "bpa": "BPA",
    "tatoo": "Tatoo",
    "tecnologia": "Tecnologia",
}


def static_app_active_page(app_key, subpath):
    if app_key == "gpsmusical":
        return "dashboards"
    if app_key == "bpa":
        return "cadastros"
    if app_key == "tatoo":
        return "cadastros"
    if app_key == "tecnologia":
        return "dashboards"
    return "dashboards"


def static_app_file(app_key, subpath=""):
    if app_key not in STATIC_APP_DIRS:
        return None
    if app_key == "gpsmusical" and subpath.startswith("shared/"):
        path = (NANOTECH_SHARED_DIR / subpath.replace("shared/", "", 1)).resolve()
        try:
            path.relative_to(NANOTECH_SHARED_DIR.resolve())
            return path
        except ValueError:
            return None
    base = STATIC_APP_DIRS[app_key].resolve()
    requested = subpath or STATIC_APP_INDEX[app_key]
    path = (base / requested).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        return None
    return path


def rewrite_static_app_paths(text, app_key, integrated=True):
    prefix = f"/apps/{app_key}" if integrated else f"/apps/{app_key}/original"
    text = text.lstrip("\ufeff")
    replacements = {
        'href="./': f'href="{prefix}/',
        "href='./": f"href='{prefix}/",
        'src="./': f'src="{prefix}/',
        "src='./": f"src='{prefix}/",
        'href="prontuario.css"': f'href="{prefix}/prontuario.css"',
        'src="prontuario.js"': f'src="{prefix}/prontuario.js"',
        'href="../shared/': f'href="{prefix}/shared/',
        'src="../shared/': f'src="{prefix}/shared/',
        'href="/"': 'href="/"',
        'href="/api/': f'href="{prefix}/api/',
        'fetch("/api/': f'fetch("{prefix}/api/',
        "fetch('/api/": f"fetch('{prefix}/api/",
        'api("/api/': f'api("{prefix}/api/',
        "api('/api/": f"api('{prefix}/api/",
        "api(`/api/": f"api(`{prefix}/api/",
        'const API_CONFIG_URL = "/api/gps/config";': f'const API_CONFIG_URL = "{prefix}/api/gps/config";',
        'const API_CONFIG_TEST_URL = "/api/gps/config/test-database";': f'const API_CONFIG_TEST_URL = "{prefix}/api/gps/config/test-database";',
        'const API_BACKUPS_URL = "/api/gps/backups";': f'const API_BACKUPS_URL = "{prefix}/api/gps/backups";',
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def static_app_navigation_bridge(app_key):
    if app_key != "gpsmusical":
        return ""
    return """
<script>
(function() {
  var tabs = {
    biblioteca: "biblioteca",
    editor: "editor",
    view: "view",
    docs: "docs",
    config: "config",
    backup: "backup"
  };

  function activateFromHash() {
    var raw = (window.location.hash || "").replace(/^#/, "");
    if (!raw) return;
    var key = raw.indexOf("docs") === 0 ? "docs" : raw.split(":")[0];
    var target = tabs[key];
    if (!target) return;
    if (typeof window.UI_showTab === "function") {
      window.UI_showTab(target);
      return;
    }
    var button = document.querySelector('[data-tab="' + target + '"]');
    if (button) button.click();
  }

  window.addEventListener("load", function() { setTimeout(activateFromHash, 80); });
  window.addEventListener("hashchange", activateFromHash);
})();
</script>
"""


def rewrite_static_app_html(text, app_key, integrated=True):
    text = rewrite_static_app_paths(text, app_key, integrated=integrated)
    text = inject_before_body_close(text, static_app_navigation_bridge(app_key))
    return apply_standalone_theme(text)


def extract_static_app_integrated(html_text, app_key, subpath=""):
    text = rewrite_static_app_html(html_text, app_key, integrated=True)
    link_tags = "\n".join(re.findall(r'<link[^>]+rel=["\']stylesheet["\'][^>]*>', text, flags=re.I))
    style_tags = "\n".join(re.findall(r"<style[^>]*>.*?</style>", text, flags=re.I | re.S))
    body_match = re.search(r"<body([^>]*)>(.*?)</body>", text, flags=re.I | re.S)
    body_attrs = body_match.group(1) if body_match else ""
    body = body_match.group(2) if body_match else text
    content = f"""
{link_tags}
{style_tags}
<div class="static-imported-app static-{html_lib.escape(app_key)}" {body_attrs}>
  {body}
</div>
"""
    return static_app_active_page(app_key, subpath), content


def static_app_response(app_key, subpath="", integrated=True):
    path = static_app_file(app_key, subpath)
    if not path or not path.exists() or path.is_dir():
        return Response("Arquivo nao encontrado.", status=404, content_type="text/plain; charset=utf-8")

    if path.suffix.lower() in {".html", ".htm"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        if integrated:
            active_page, app_content = extract_static_app_integrated(text, app_key, subpath)
            return render_template(
                "integrated_app.html",
                active_page=active_page,
                app_nome=STATIC_APP_NAMES[app_key],
                app_style="",
                app_content=app_content,
                **portal_context(),
            )
        return rewrite_static_app_html(text, app_key, integrated=False)

    if path.suffix.lower() == ".js":
        text = path.read_text(encoding="utf-8", errors="replace")
        text = rewrite_static_app_paths(text, app_key, integrated=integrated)
        return Response(text, content_type="text/javascript; charset=utf-8")

    return send_from_directory(path.parent, path.name)


@app.route("/apps/gpsmusical")
@login_required
def gpsmusical_static_root():
    return static_app_response("gpsmusical")


@app.route("/apps/gpsmusical/original")
@login_required
def gpsmusical_original_root():
    return static_app_response("gpsmusical", integrated=False)


@app.route("/apps/gpsmusical/original/<path:subpath>")
@login_required
def gpsmusical_original_static(subpath):
    return static_app_response("gpsmusical", subpath, integrated=False)


@app.route("/apps/gpsmusical/<path:subpath>")
@login_required
def gpsmusical_static(subpath):
    return static_app_response("gpsmusical", subpath)


@app.route("/apps/bpa")
@login_required
def bpa_static_root():
    return static_app_response("bpa")


@app.route("/apps/bpa/original")
@login_required
def bpa_original_root():
    return static_app_response("bpa", integrated=False)


@app.route("/apps/bpa/original/<path:subpath>")
@login_required
def bpa_original_static(subpath):
    return static_app_response("bpa", subpath, integrated=False)


@app.route("/apps/bpa/<path:subpath>")
@login_required
def bpa_static(subpath):
    return static_app_response("bpa", subpath)


@app.route("/apps/tatoo")
@login_required
def tatoo_static_root():
    return static_app_response("tatoo")


@app.route("/apps/tatoo/original")
@login_required
def tatoo_original_root():
    return static_app_response("tatoo", integrated=False)


@app.route("/apps/tatoo/original/<path:subpath>")
@login_required
def tatoo_original_static(subpath):
    return static_app_response("tatoo", subpath, integrated=False)


@app.route("/apps/tatoo/<path:subpath>")
@login_required
def tatoo_static(subpath):
    return static_app_response("tatoo", subpath)


# ---------------------------------------------------------------------------
# Tecnologia: monitoramento da rede local
# ---------------------------------------------------------------------------
def technology_json_value(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def technology_db_timestamp_iso(value):
    """Serializa DATETIME do banco, gravado em UTC, sem perder o fuso na API."""
    if not hasattr(value, "isoformat"):
        return str(value or "")
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    else:
        value = value.astimezone(dt.UTC)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def technology_utc_cutoff(hours):
    return dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(hours=hours)


TECHNOLOGY_LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def technology_printer_week_start(now=None):
    current = now or dt.datetime.now(dt.UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.UTC)
    local_now = current.astimezone(TECHNOLOGY_LOCAL_TIMEZONE)
    week_start_date = local_now.date() - dt.timedelta(days=(local_now.weekday() + 1) % 7)
    week_start_local = dt.datetime.combine(
        week_start_date, dt.time.min, tzinfo=TECHNOLOGY_LOCAL_TIMEZONE
    )
    return local_now, week_start_local.astimezone(dt.UTC).replace(tzinfo=None)


def technology_printer_page_usage(rows, now=None):
    """Converte o contador acumulado do Printer-MIB em totais diários."""
    local_now, _ = technology_printer_week_start(now)
    today = local_now.date()
    week_start = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    dates = [week_start + dt.timedelta(days=offset) for offset in range((today - week_start).days + 1)]
    totals = {day: 0 for day in dates}
    day_labels = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
    previous_count = None
    comparisons = 0
    current_count = None
    coverage_started_at = None

    for row in rows:
        details = technology_json_value(row.get("detalhes"))
        telemetry = details.get("telemetry") if isinstance(details.get("telemetry"), dict) else {}
        try:
            page_count = int(telemetry.get("pageCount"))
        except (TypeError, ValueError):
            continue
        checked_at = row.get("verificado_em")
        if page_count < 0 or not isinstance(checked_at, dt.datetime):
            continue
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=dt.UTC)
        else:
            checked_at = checked_at.astimezone(dt.UTC)
        checked_date = checked_at.astimezone(TECHNOLOGY_LOCAL_TIMEZONE).date()
        if coverage_started_at is None:
            coverage_started_at = checked_at

        if previous_count is not None and checked_date in totals:
            # Contadores podem reiniciar após manutenção. Nesse intervalo a
            # diferença é desconhecida e nunca deve virar impressão negativa.
            totals[checked_date] += max(0, page_count - previous_count)
            comparisons += 1
        previous_count = page_count
        current_count = page_count

    return {
        "periodStart": week_start.isoformat(),
        "periodEnd": today.isoformat(),
        "todayPages": totals.get(today, 0),
        "weekPages": sum(totals.values()),
        "currentCounter": current_count,
        "hasComparisons": comparisons > 0,
        "coverageStartedAt": technology_db_timestamp_iso(coverage_started_at) if coverage_started_at else None,
        "todayComplete": bool(
            coverage_started_at
            and coverage_started_at.astimezone(TECHNOLOGY_LOCAL_TIMEZONE)
            <= dt.datetime.combine(today, dt.time.min, tzinfo=TECHNOLOGY_LOCAL_TIMEZONE)
        ),
        "days": [
            {"date": day.isoformat(), "label": day_labels[day.weekday()], "pages": totals[day]}
            for day in dates
        ],
    }


def technology_public_metric(row, prefix=""):
    if not row or not row.get(f"{prefix}status"):
        return None
    checked_at = row.get(f"{prefix}verificado_em")
    details = technology_json_value(row.get(f"{prefix}detalhes"))
    telemetry = details.get("telemetry") if isinstance(details.get("telemetry"), dict) else None
    return {
        "status": row.get(f"{prefix}status"),
        "latencyMs": float(row[f"{prefix}latencia_ms"]) if row.get(f"{prefix}latencia_ms") is not None else None,
        "packetLossPct": float(row.get(f"{prefix}perda_pct") or 0),
        "jitterMs": float(row[f"{prefix}jitter_ms"]) if row.get(f"{prefix}jitter_ms") is not None else None,
        "serviceOk": None if row.get(f"{prefix}servico_ok") is None else bool(row.get(f"{prefix}servico_ok")),
        "message": row.get(f"{prefix}mensagem") or "",
        "checkedAt": technology_db_timestamp_iso(checked_at),
        "telemetry": telemetry,
        "addresses": details.get("addresses") if isinstance(details.get("addresses"), list) else [],
        "activeAddress": details.get("activeAddress") or "",
    }


def technology_public_device(row):
    return {
        "id": int(row["id"]),
        "nome": row.get("nome") or "",
        "tipo": row.get("tipo") or "OUTRO",
        "host": row.get("host") or "",
        "networkAddresses": device_network_addresses(row),
        "porta": int(row["porta"]) if row.get("porta") is not None else None,
        "sonda": row.get("sonda") or "ICMP",
        "localizacao": row.get("localizacao") or "",
        "observacoes": row.get("observacoes") or "",
        "critico": bool(row.get("critico")),
        "ativo": bool(row.get("ativo")),
        "latenciaAlertaMs": float(row.get("latencia_alerta_ms") or 80),
        "perdaAlertaPct": float(row.get("perda_alerta_pct") or 5),
        "downloadAlertMbps": float(row.get("download_alerta_mbps") or 50),
        "uploadAlertMbps": float(row.get("upload_alerta_mbps") or 10),
        "cpuAlertPct": float(row.get("cpu_alerta_pct") or 90),
        "memoryAlertPct": float(row.get("memoria_alerta_pct") or 90),
        "diskAlertPct": float(row.get("disco_alerta_pct") or 90),
        "trafficAlertMbps": float(row.get("trafego_alerta_mbps") or 100),
        "snmpPort": int(row.get("snmp_port") or 161),
        "hasSnmpCommunity": bool(row.get("snmp_community")),
        "agentPort": int(row["agente_porta"]) if row.get("agente_porta") is not None else None,
        "agentPath": row.get("agente_path") or "/metrics",
        "availability24h": float(row["disponibilidade_24h"]) if row.get("disponibilidade_24h") is not None else None,
        "avgLatency24h": float(row["latencia_media_24h"]) if row.get("latencia_media_24h") is not None else None,
        "avgLoss24h": float(row["perda_media_24h"]) if row.get("perda_media_24h") is not None else None,
        "checks24h": int(row.get("checagens_24h") or 0),
        "ultimaMetrica": technology_public_metric(row, "ultima_"),
    }


def technology_device_identity_key(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^A-Z0-9]+", "", text.encode("ascii", "ignore").decode("ascii").upper())


def technology_registered_device_index(rows, exclude_device_id=None):
    by_host = {}
    by_name = {}
    for row in rows:
        if exclude_device_id is not None and int(row.get("id") or 0) == int(exclude_device_id):
            continue
        try:
            addresses = device_network_addresses(row)
        except (TypeError, ValueError):
            addresses = [{"host": str(row.get("host") or "").strip()}]
        for address in addresses:
            if address.get("host"):
                by_host.setdefault(address["host"], row)

        details = technology_json_value(row.get("ultima_detalhes"))
        telemetry = details.get("telemetry") if isinstance(details.get("telemetry"), dict) else {}
        netbios = details.get("netbios") if isinstance(details.get("netbios"), dict) else {}
        identity_names = [row.get("nome"), telemetry.get("systemName"), netbios.get("name")]
        for name in identity_names:
            identity_key = technology_device_identity_key(name)
            if identity_key:
                by_name.setdefault(identity_key, row)
    return {"hosts": by_host, "names": by_name}


def technology_registered_device_hosts(rows):
    return {
        host: row.get("nome") or row.get("host") or "Equipamento"
        for host, row in technology_registered_device_index(rows)["hosts"].items()
    }


def technology_registered_device_match(index, host="", identity_name=""):
    registered = (index.get("hosts") or {}).get(str(host or "").strip())
    if registered:
        return registered
    identity_key = technology_device_identity_key(identity_name)
    return (index.get("names") or {}).get(identity_key) if identity_key else None


def technology_device_address_conflict(device, rows, exclude_device_id=None):
    index = technology_registered_device_index(rows, exclude_device_id=exclude_device_id)
    for address in device_network_addresses(device):
        registered = technology_registered_device_match(index, host=address.get("host"))
        if registered:
            return address.get("host"), registered
    return None


def technology_riob_smtp_config():
    schema = str(os.environ.get("RIOB_DB_NAME") or "riobranco").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", schema):
        return None
    try:
        account_id = int(os.environ.get("TECH_ALERT_EMAIL_ACCOUNT_ID") or 0)
    except (TypeError, ValueError):
        account_id = 0
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            f"""
            SELECT id, account_name, email_user, email_pass, smtp_host,
                   smtp_port, smtp_use_tls
            FROM `{schema}`.gestor_email_config
            WHERE COALESCE(enabled, 1)=1
              AND COALESCE(smtp_host, '') <> ''
              AND COALESCE(email_user, '') <> ''
              AND COALESCE(email_pass, '') <> ''
            ORDER BY (id=%s) DESC, id ASC
            LIMIT 1
            """,
            (account_id,),
        )
        row = cur.fetchone()
    except mysql.connector.Error:
        row = None
    finally:
        cur.close()
        conn.close()
    if not row:
        return None
    return {
        "host": str(row.get("smtp_host") or "").strip(),
        "port": int(row.get("smtp_port") or 587),
        "user": str(row.get("email_user") or "").strip(),
        "password": str(row.get("email_pass") or ""),
        "sender": str(row.get("email_user") or "").strip(),
        "useTls": bool(row.get("smtp_use_tls")),
        "source": "riob",
        "accountName": str(row.get("account_name") or f"Conta {row.get('id')}").strip(),
    }


def technology_email_config():
    host = str(os.environ.get("SMTP_HOST") or "").strip()
    user = str(os.environ.get("SMTP_USER") or "").strip()
    password = str(os.environ.get("SMTP_PASSWORD") or "")
    sender = str(os.environ.get("SMTP_FROM") or user).strip()
    recipient = str(os.environ.get("TECH_ALERT_EMAIL_TO") or TECH_ALERT_DEFAULT_TO).strip()
    try:
        port = int(os.environ.get("SMTP_PORT") or 587)
    except (TypeError, ValueError):
        port = 587
    use_tls = str(os.environ.get("SMTP_USE_TLS", "1")).strip().lower() not in {"0", "false", "nao", "não", "off"}
    config = {
        "host": host, "port": port, "user": user, "password": password,
        "sender": sender, "useTls": use_tls, "source": "environment",
        "accountName": "SMTP do ambiente",
    } if host else (technology_riob_smtp_config() or {
        "host": "", "port": port, "user": "", "password": "",
        "sender": "", "useTls": use_tls, "source": "none", "accountName": "",
    })
    config["recipient"] = recipient
    config["configured"] = bool(
        config["host"] and config["sender"] and recipient
        and (not config["user"] or config["password"])
    )
    return config


def send_technology_email(subject, body):
    config = technology_email_config()
    if not config["configured"]:
        raise RuntimeError("SMTP não configurado: informe servidor, remetente e credencial")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["sender"]
    message["To"] = config["recipient"]
    message.set_content(body)
    context = ssl.create_default_context()
    if config["port"] == 465:
        client = smtplib.SMTP_SSL(config["host"], config["port"], timeout=15, context=context)
    else:
        client = smtplib.SMTP(config["host"], config["port"], timeout=15)
    with client:
        if config["port"] != 465 and config["useTls"]:
            client.starttls(context=context)
        if config["user"]:
            client.login(config["user"], config["password"])
        client.send_message(message)
    return config["recipient"]


def technology_alert_email_body(actions, now=None):
    now = now or dt.datetime.now()
    lines = [
        "Monitoramento de Tecnologia - NanotechSoft",
        f"Data: {now.strftime('%d/%m/%Y %H:%M:%S')}",
        "",
    ]
    for action in actions:
        description = str(action.get("description") or "").strip()
        if description:
            lines.append(f"{action['type']}: {action['deviceName']} ({action['host']}) - {description}.")
        else:
            lines.append(
                f"{action['type']}: {action['deviceName']} ({action['host']}) - "
                f"{action['label']} em {action['value']:.1f}% (limite {action['limit']:.1f}%)."
            )
    lines.extend([
        "",
        "Abra o módulo Tecnologia do portal para consultar a medição e o equipamento.",
        "O aviso é repetido somente após o intervalo configurado enquanto o problema continuar.",
    ])
    return "\n".join(lines)


def technology_resource_alert_action(previous, value, limit, now, retry_after, reminder_after, recovery_margin):
    active = bool(previous and previous.get("ativo"))
    if value >= limit:
        if not active:
            return "ALERTA"
        if previous.get("ultimo_email_em") is None:
            last_attempt = previous.get("ultima_tentativa_em")
            if not last_attempt or now - last_attempt >= retry_after:
                return "ALERTA"
        elif now - previous["ultimo_email_em"] >= reminder_after:
            return "LEMBRETE"
    elif active and value <= max(0, limit - recovery_margin):
        return "RECUPERADO"
    return None


def technology_alert_telemetry(device, result):
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    telemetry = dict(details.get("telemetry")) if isinstance(details.get("telemetry"), dict) else {}
    if str(device.get("tipo") or "").upper() == "INTERNET":
        offline = str(result.get("status") or "").upper() == "OFFLINE"
        telemetry["internetDownState"] = 100 if offline else 0
        telemetry["internetDownAlertDescription"] = "o link de internet está sem resposta"
        telemetry["internetDownRecoveryDescription"] = "o link de internet voltou a responder"
    if str(device.get("tipo") or "").upper() == "ROTEADOR":
        status = str(result.get("status") or "").upper()
        failed = status in {"OFFLINE", "DEGRADADO"}
        reason = str(result.get("message") or "sem resposta").strip()
        telemetry["gatewayFailureState"] = 100 if failed else 0
        telemetry["gatewayFailureAlertDescription"] = (
            f"o gateway está {'sem resposta' if status == 'OFFLINE' else f'instável: {reason}'}"
        )
        telemetry["gatewayFailureRecoveryDescription"] = "o gateway voltou a responder normalmente"
    return telemetry


def process_technology_resource_alerts(devices, results, now=None):
    """Atualiza os limites e envia um único e-mail consolidado por coleta."""
    now = now or dt.datetime.now()
    try:
        reminder_hours = max(1, float(os.environ.get("TECH_ALERT_REMINDER_HOURS") or 6))
    except (TypeError, ValueError):
        reminder_hours = 6
    try:
        recovery_margin = max(0, float(os.environ.get("TECH_ALERT_RECOVERY_MARGIN_PCT") or 5))
    except (TypeError, ValueError):
        recovery_margin = 5
    retry_after = dt.timedelta(minutes=15)
    reminder_after = dt.timedelta(hours=reminder_hours)
    actions = []
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        for device, result in zip(devices, results):
            telemetry = technology_alert_telemetry(device, result)
            for resource, (metric_key, limit_key, label, default_limit) in TECH_ALERT_RESOURCES.items():
                raw_value = telemetry.get(metric_key)
                if raw_value is None:
                    continue
                try:
                    value = float(raw_value)
                    limit = float(device.get(limit_key) or default_limit) if limit_key else float(default_limit)
                except (TypeError, ValueError):
                    continue
                cur.execute(
                    "SELECT * FROM tecnologia_alertas_recursos WHERE dispositivo_id=%s AND recurso=%s",
                    (int(device["id"]), resource),
                )
                previous = cur.fetchone()
                active = bool(previous and previous.get("ativo"))
                action_type = technology_resource_alert_action(
                    previous, value, limit, now, retry_after, reminder_after, recovery_margin,
                )
                if value >= limit:
                    if previous:
                        cur.execute(
                            """
                            UPDATE tecnologia_alertas_recursos
                            SET ativo=1, valor_atual=%s, limite_pct=%s,
                                disparado_em=IF(%s=0, %s, disparado_em),
                                recuperado_em=IF(%s=0, NULL, recuperado_em),
                                ultimo_email_em=IF(%s=0, NULL, ultimo_email_em),
                                ultima_tentativa_em=IF(%s IS NULL, ultima_tentativa_em, %s),
                                ultimo_erro=IF(%s=0, '', ultimo_erro)
                            WHERE dispositivo_id=%s AND recurso=%s
                            """,
                            (
                                value, limit, int(active), now, int(active), int(active),
                                action_type, now, int(active), int(device["id"]), resource,
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO tecnologia_alertas_recursos
                                (dispositivo_id, recurso, ativo, valor_atual, limite_pct,
                                 disparado_em, ultima_tentativa_em)
                            VALUES (%s, %s, 1, %s, %s, %s, %s)
                            """,
                            (int(device["id"]), resource, value, limit, now, now),
                        )
                elif active and value <= max(0, limit - recovery_margin):
                    action_type = "RECUPERADO"
                    cur.execute(
                        """
                        UPDATE tecnologia_alertas_recursos
                        SET ativo=0, valor_atual=%s, limite_pct=%s, recuperado_em=%s,
                            ultima_tentativa_em=%s, ultimo_erro=''
                        WHERE dispositivo_id=%s AND recurso=%s
                        """,
                        (value, limit, now, now, int(device["id"]), resource),
                    )
                elif previous:
                    cur.execute(
                        """
                        UPDATE tecnologia_alertas_recursos SET valor_atual=%s, limite_pct=%s
                        WHERE dispositivo_id=%s AND recurso=%s
                        """,
                        (value, limit, int(device["id"]), resource),
                    )
                if action_type:
                    description = ""
                    description_prefix = {
                        "INTERNET_QUEDA": "internetDown",
                        "LINK_LENTO": "linkSlow",
                        "GATEWAY_FALHA": "gatewayFailure",
                    }.get(resource)
                    if description_prefix:
                        description = str(
                            telemetry.get(
                                f"{description_prefix}{'RecoveryDescription' if action_type == 'RECUPERADO' else 'AlertDescription'}"
                            ) or ""
                        )
                    actions.append({
                        "deviceId": int(device["id"]),
                        "deviceName": device.get("nome") or device.get("host") or "Equipamento",
                        "host": device.get("host") or "", "resource": resource,
                        "label": label, "value": value, "limit": limit, "type": action_type,
                        "description": description,
                    })
        conn.commit()
        if not actions:
            return []
        has_problem = any(item["type"] != "RECUPERADO" for item in actions)
        subject = "[NanotechSoft] Alerta de internet ou recursos" if has_problem else "[NanotechSoft] Monitoramento normalizado"
        try:
            send_technology_email(subject, technology_alert_email_body(actions, now=now))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:500]
            for item in actions:
                cur.execute(
                    "UPDATE tecnologia_alertas_recursos SET ultimo_erro=%s WHERE dispositivo_id=%s AND recurso=%s",
                    (error, item["deviceId"], item["resource"]),
                )
            conn.commit()
            print(f"[tecnologia] e-mail de alerta não enviado: {error}", file=sys.stderr)
        else:
            for item in actions:
                cur.execute(
                    """
                    UPDATE tecnologia_alertas_recursos SET ultimo_email_em=%s, ultimo_erro=''
                    WHERE dispositivo_id=%s AND recurso=%s
                    """,
                    (now, item["deviceId"], item["resource"]),
                )
            conn.commit()
        return actions
    finally:
        cur.close()
        conn.close()


def get_technology_alert_status():
    config = technology_email_config()
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT COUNT(CASE WHEN ativo=1 THEN 1 END) AS ativos,
               MAX(ultimo_email_em) AS ultimo_email_em
        FROM tecnologia_alertas_recursos
        """
    )
    summary = cur.fetchone() or {}
    cur.execute(
        "SELECT ultimo_erro FROM tecnologia_alertas_recursos WHERE ultimo_erro <> '' ORDER BY updated_at DESC LIMIT 1"
    )
    error = cur.fetchone()
    cur.close()
    conn.close()
    last_email = summary.get("ultimo_email_em")
    return {
        "configured": config["configured"], "recipient": config["recipient"],
        "sender": config["sender"], "source": config["source"],
        "accountName": config["accountName"],
        "activeCount": int(summary.get("ativos") or 0),
        "lastEmailAt": last_email.isoformat(timespec="seconds") if last_email else None,
        "lastError": (error or {}).get("ultimo_erro") or "",
    }


def get_technology_devices(active_only=False):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    active_filter = "WHERE d.ativo=1" if active_only else ""
    cur.execute(
        f"""
        SELECT d.*,
               latest.status AS ultima_status,
               latest.latencia_ms AS ultima_latencia_ms,
               latest.perda_pct AS ultima_perda_pct,
               latest.jitter_ms AS ultima_jitter_ms,
               latest.servico_ok AS ultima_servico_ok,
               latest.mensagem AS ultima_mensagem,
               latest.detalhes AS ultima_detalhes,
               latest.verificado_em AS ultima_verificado_em,
               stats.disponibilidade_24h,
               stats.latencia_media_24h,
               stats.perda_media_24h,
               stats.checagens_24h
        FROM tecnologia_dispositivos d
        LEFT JOIN tecnologia_metricas latest ON latest.id = (
            SELECT m.id FROM tecnologia_metricas m
            WHERE m.dispositivo_id=d.id
            ORDER BY m.verificado_em DESC, m.id DESC LIMIT 1
        )
        LEFT JOIN (
            SELECT dispositivo_id,
                   ROUND(AVG(status <> 'OFFLINE') * 100, 2) AS disponibilidade_24h,
                   ROUND(AVG(latencia_ms), 2) AS latencia_media_24h,
                   ROUND(AVG(perda_pct), 2) AS perda_media_24h,
                   COUNT(*) AS checagens_24h
            FROM tecnologia_metricas
            WHERE verificado_em >= NOW() - INTERVAL 24 HOUR
            GROUP BY dispositivo_id
        ) stats ON stats.dispositivo_id=d.id
        {active_filter}
        ORDER BY FIELD(d.tipo, 'INTERNET', 'ROTEADOR', 'SERVIDOR', 'COMPUTADOR', 'NOTEBOOK', 'NVR', 'RELOGIO_PONTO', 'IMPRESSORA', 'OUTRO'), d.nome
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def technology_public_speed(row):
    if not row:
        return None
    checked_at = row.get("verificado_em")
    return {
        "id": int(row["id"]),
        "deviceId": int(row["dispositivo_id"]),
        "status": row.get("status") or "FALHA",
        "downloadMbps": float(row["download_mbps"]) if row.get("download_mbps") is not None else None,
        "uploadMbps": float(row["upload_mbps"]) if row.get("upload_mbps") is not None else None,
        "latencyMs": float(row["latencia_ms"]) if row.get("latencia_ms") is not None else None,
        "message": row.get("mensagem") or "",
        "checkedAt": technology_db_timestamp_iso(checked_at),
    }


def get_latest_technology_speed():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT v.*, d.download_alerta_mbps, d.upload_alerta_mbps
        FROM tecnologia_velocidade v
        JOIN tecnologia_dispositivos d ON d.id=v.dispositivo_id
        ORDER BY v.verificado_em DESC, v.id DESC LIMIT 1
        """
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    result = technology_public_speed(row)
    result["downloadAlertMbps"] = float(row.get("download_alerta_mbps") or 50)
    result["uploadAlertMbps"] = float(row.get("upload_alerta_mbps") or 10)
    return result


def process_technology_link_speed_alert(internet, speed):
    if not speed or str(speed.get("status") or "").upper() == "FALHA":
        return []
    download = speed.get("downloadMbps")
    upload = speed.get("uploadMbps")
    if download is None or upload is None:
        return []
    minimum_download = float(internet.get("download_alerta_mbps") or 50)
    minimum_upload = float(internet.get("upload_alerta_mbps") or 10)
    low_download = float(download) < minimum_download
    low_upload = float(upload) < minimum_upload
    low_parts = []
    if low_download:
        low_parts.append(f"download baixo: {float(download):.1f} Mbps, mínimo {minimum_download:.1f} Mbps")
    if low_upload:
        low_parts.append(f"upload baixo: {float(upload):.1f} Mbps, mínimo {minimum_upload:.1f} Mbps")
    telemetry = {
        "linkSlowState": 100 if low_download or low_upload else 0,
        "linkSlowAlertDescription": "; ".join(low_parts),
        "linkSlowRecoveryDescription": (
            f"velocidade normalizada: download {float(download):.1f} Mbps e "
            f"upload {float(upload):.1f} Mbps"
        ),
    }
    return process_technology_resource_alerts(
        [internet],
        [{"status": speed.get("status"), "details": {"telemetry": telemetry}}],
    )


def collect_technology_speed(force=False):
    with _technology_speed_lock:
        interval = max(300, int(os.environ.get("TECH_SPEED_INTERVAL_SECONDS", "1800")))
        devices = get_technology_devices(active_only=True)
        internet = next((row for row in devices if row.get("tipo") == "INTERNET"), None)
        if not internet:
            raise ValueError("cadastre um equipamento do tipo INTERNET para medir o link")
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT *, TIMESTAMPDIFF(SECOND, verificado_em, NOW()) AS age_seconds
            FROM tecnologia_velocidade
            WHERE dispositivo_id=%s ORDER BY verificado_em DESC, id DESC LIMIT 1
            """,
            (int(internet["id"]),),
        )
        latest = cur.fetchone()
        if not force and latest and latest.get("verificado_em"):
            age = max(0, float(latest.get("age_seconds") or 0))
            if age < interval:
                cur.close()
                conn.close()
                public_speed = technology_public_speed(latest)
                process_technology_link_speed_alert(internet, public_speed)
                return public_speed
        result = measure_internet_speed()
        if result.get("status") == "OK":
            low_download = float(result.get("downloadMbps") or 0) < float(internet.get("download_alerta_mbps") or 50)
            low_upload = float(result.get("uploadMbps") or 0) < float(internet.get("upload_alerta_mbps") or 10)
            if low_download or low_upload:
                result["status"] = "DEGRADADO"
        cur.execute(
            """
            INSERT INTO tecnologia_velocidade
                (dispositivo_id, status, download_mbps, upload_mbps, latencia_ms, mensagem, detalhes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                int(internet["id"]), result.get("status") or "FALHA",
                result.get("downloadMbps"), result.get("uploadMbps"), result.get("latencyMs"),
                result.get("message") or "", json.dumps(result.get("details") or {}, ensure_ascii=False),
            ),
        )
        speed_id = int(cur.lastrowid)
        cur.execute("DELETE FROM tecnologia_velocidade WHERE verificado_em < NOW() - INTERVAL 90 DAY")
        conn.commit()
        cur.execute("SELECT * FROM tecnologia_velocidade WHERE id=%s", (speed_id,))
        saved = cur.fetchone()
        cur.close()
        conn.close()
        public_speed = technology_public_speed(saved)
        process_technology_link_speed_alert(internet, public_speed)
        return public_speed


def collect_technology_metrics(device_ids=None):
    requested = {int(item) for item in (device_ids or [])}
    with _technology_probe_lock:
        rows = get_technology_devices(active_only=True)
        if requested:
            rows = [row for row in rows if int(row["id"]) in requested]
        if not rows:
            return []
        workers = min(16, len(rows))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(probe_device, rows))
        conn = get_conn()
        cur = conn.cursor()
        for device, result in zip(rows, results):
            cur.execute(
                """
                INSERT INTO tecnologia_metricas
                    (dispositivo_id, status, latencia_ms, perda_pct, jitter_ms,
                     servico_ok, mensagem, detalhes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    int(device["id"]),
                    result["status"],
                    result.get("latencyMs"),
                    result.get("packetLossPct") or 0,
                    result.get("jitterMs"),
                    result.get("serviceOk"),
                    result.get("message") or "",
                    json.dumps(result.get("details") or {}, ensure_ascii=False),
                ),
            )
        cur.execute("DELETE FROM tecnologia_metricas WHERE verificado_em < NOW() - INTERVAL 90 DAY")
        conn.commit()
        cur.close()
        conn.close()
        process_technology_resource_alerts(rows, results)
        return [
            {"deviceId": int(device["id"]), **result}
            for device, result in zip(rows, results)
        ]


def _technology_monitor_loop():
    interval = max(15, int(os.environ.get("TECH_MONITOR_INTERVAL_SECONDS", "60")))
    while True:
        try:
            ensure_database()
            collect_technology_metrics()
            collect_technology_speed()
        except Exception as exc:
            print(f"[tecnologia] falha na coleta: {type(exc).__name__}: {exc}", file=sys.stderr)
        time.sleep(interval)


def start_technology_monitor():
    global _technology_monitor_thread
    with _technology_monitor_lock:
        if _technology_monitor_thread and _technology_monitor_thread.is_alive():
            return
        _technology_monitor_thread = threading.Thread(
            target=_technology_monitor_loop,
            name="tecnologia-monitor",
            daemon=True,
        )
        _technology_monitor_thread.start()


def technology_admin_or_error():
    usuario = current_user_or_logout()
    if not usuario or not user_is_admin(usuario):
        return jsonify({"erro": "somente administradores podem alterar o monitoramento"}), 403
    return None


@app.route("/apps/tecnologia/api/overview")
@login_required
def tecnologia_overview_api():
    start_technology_monitor()
    devices = [technology_public_device(row) for row in get_technology_devices()]
    speed = get_latest_technology_speed()
    return jsonify({
        "devices": devices,
        "speed": speed,
        "emailAlerts": get_technology_alert_status(),
        "diagnosis": build_network_diagnosis(devices, speed),
        "monitorIntervalSeconds": max(15, int(os.environ.get("TECH_MONITOR_INTERVAL_SECONDS", "60"))),
        "speedIntervalSeconds": max(300, int(os.environ.get("TECH_SPEED_INTERVAL_SECONDS", "1800"))),
        "subnet": "192.168.200.0/24",
    })


@app.route("/apps/tecnologia/api/alerts/test-email", methods=["POST"])
@login_required
def tecnologia_alert_test_email_api():
    denied = technology_admin_or_error()
    if denied:
        return denied
    now = dt.datetime.now()
    try:
        recipient = send_technology_email(
            "[NanotechSoft] Teste dos alertas de Tecnologia",
            "\n".join([
                "Monitoramento de Tecnologia - NanotechSoft",
                f"Data: {now.strftime('%d/%m/%Y %H:%M:%S')}",
                "",
                "Este é um teste da configuração de e-mail.",
                "Os alertas de CPU, memória RAM e disco estão habilitados.",
            ]),
        )
    except Exception as exc:
        return jsonify({"erro": f"Não foi possível enviar: {exc}"}), 400
    return jsonify({"ok": True, "recipient": recipient})


@app.route("/apps/tecnologia/api/probe", methods=["POST"])
@login_required
def tecnologia_probe_api():
    payload = request.get_json(silent=True) or {}
    ids = payload.get("deviceIds") or []
    if not isinstance(ids, list):
        return jsonify({"erro": "a lista de equipamentos é inválida"}), 400
    try:
        results = collect_technology_metrics(ids)
    except (TypeError, ValueError):
        return jsonify({"erro": "a lista de equipamentos é inválida"}), 400
    devices = [technology_public_device(row) for row in get_technology_devices()]
    speed = get_latest_technology_speed()
    return jsonify({"results": results, "devices": devices, "speed": speed, "diagnosis": build_network_diagnosis(devices, speed)})


@app.route("/apps/tecnologia/api/speed-test", methods=["POST"])
@login_required
def tecnologia_speed_test_api():
    try:
        speed = collect_technology_speed(force=True)
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    devices = [technology_public_device(row) for row in get_technology_devices()]
    return jsonify({"speed": speed, "diagnosis": build_network_diagnosis(devices, speed)})


@app.route("/apps/tecnologia/api/speed-history")
@login_required
def tecnologia_speed_history_api():
    try:
        hours = min(2160, max(1, int(request.args.get("hours") or 168)))
    except (TypeError, ValueError):
        return jsonify({"erro": "período inválido"}), 400
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cutoff = technology_utc_cutoff(hours)
    cur.execute(
        """
        SELECT id, dispositivo_id, verificado_em, status, download_mbps,
               upload_mbps, latencia_ms, mensagem
        FROM tecnologia_velocidade
        WHERE verificado_em >= %s
        ORDER BY verificado_em ASC, id ASC LIMIT 3000
        """,
        (cutoff,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"metrics": [technology_public_speed(row) for row in rows]})


@app.route("/apps/tecnologia/api/history")
@login_required
def tecnologia_history_api():
    try:
        device_id = int(request.args.get("deviceId") or 0)
        hours = min(720, max(1, int(request.args.get("hours") or 24)))
    except (TypeError, ValueError):
        return jsonify({"erro": "filtro de histórico inválido"}), 400
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cutoff = technology_utc_cutoff(hours)
    cur.execute(
        """
        SELECT id, dispositivo_id, verificado_em, status, latencia_ms,
               perda_pct, jitter_ms, servico_ok, mensagem, detalhes
        FROM tecnologia_metricas
        WHERE dispositivo_id=%s AND verificado_em >= %s
        ORDER BY verificado_em ASC, id ASC
        LIMIT 3000
        """,
        (device_id, cutoff),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"metrics": [
        {
            "id": int(row["id"]),
            "deviceId": int(row["dispositivo_id"]),
            "checkedAt": technology_db_timestamp_iso(row["verificado_em"]),
            "status": row["status"],
            "latencyMs": float(row["latencia_ms"]) if row.get("latencia_ms") is not None else None,
            "packetLossPct": float(row.get("perda_pct") or 0),
            "jitterMs": float(row["jitter_ms"]) if row.get("jitter_ms") is not None else None,
            "serviceOk": None if row.get("servico_ok") is None else bool(row.get("servico_ok")),
            "message": row.get("mensagem") or "",
            "telemetry": (technology_json_value(row.get("detalhes")).get("telemetry")),
        }
        for row in rows
    ]})


@app.route("/apps/tecnologia/api/devices/<int:device_id>/print-usage")
@login_required
def tecnologia_printer_usage_api(device_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome, tipo FROM tecnologia_dispositivos WHERE id=%s LIMIT 1",
        (device_id,),
    )
    device = cur.fetchone()
    if not device:
        cur.close()
        conn.close()
        return jsonify({"erro": "equipamento não encontrado"}), 404
    if device.get("tipo") != "IMPRESSORA":
        cur.close()
        conn.close()
        return jsonify({"erro": "o equipamento selecionado não é uma impressora"}), 400

    local_now, week_start_utc = technology_printer_week_start()
    cur.execute(
        """
        SELECT verificado_em, detalhes
        FROM tecnologia_metricas
        WHERE dispositivo_id=%s
          AND verificado_em < %s
          AND JSON_EXTRACT(detalhes, '$.telemetry.pageCount') IS NOT NULL
        ORDER BY verificado_em DESC, id DESC
        LIMIT 1
        """,
        (device_id, week_start_utc),
    )
    baseline = cur.fetchone()
    cur.execute(
        """
        SELECT verificado_em, detalhes
        FROM tecnologia_metricas
        WHERE dispositivo_id=%s
          AND verificado_em >= %s
          AND JSON_EXTRACT(detalhes, '$.telemetry.pageCount') IS NOT NULL
        ORDER BY verificado_em ASC, id ASC
        LIMIT 15000
        """,
        (device_id, week_start_utc),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if baseline:
        rows.insert(0, baseline)
    return jsonify(technology_printer_page_usage(rows, now=local_now))


@app.route("/apps/tecnologia/api/devices", methods=["POST"])
@login_required
def tecnologia_create_device_api():
    denied = technology_admin_or_error()
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    payload.pop("preserveSnmpCommunity", None)
    try:
        data = normalize_device_payload(payload)
    except (TypeError, ValueError) as exc:
        return jsonify({"erro": str(exc)}), 400
    existing_rows = get_technology_devices()
    conflict = technology_device_address_conflict(data, existing_rows)
    if conflict:
        host, registered = conflict
        return jsonify({
            "erro": f"o endereço {host} já pertence a {registered.get('nome') or registered.get('host')}"
        }), 409
    identity_name = str(payload.get("identityName") or "").strip()
    if identity_name:
        registered = technology_registered_device_match(
            technology_registered_device_index(existing_rows), identity_name=identity_name
        )
        if registered:
            return jsonify({
                "erro": f"a identidade {identity_name} já pertence a {registered.get('nome') or registered.get('host')}"
            }), 409
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO tecnologia_dispositivos
                (nome, tipo, host, enderecos_adicionais, porta, sonda, localizacao, observacoes,
                 critico, ativo, latencia_alerta_ms, perda_alerta_pct,
                 download_alerta_mbps, upload_alerta_mbps, cpu_alerta_pct,
                 memoria_alerta_pct, disco_alerta_pct, trafego_alerta_mbps,
                 snmp_community, snmp_port, agente_porta, agente_path)
            VALUES (%(nome)s, %(tipo)s, %(host)s, %(enderecos_adicionais)s, %(porta)s, %(sonda)s,
                    %(localizacao)s, %(observacoes)s, %(critico)s, %(ativo)s,
                    %(latencia_alerta_ms)s, %(perda_alerta_pct)s,
                    %(download_alerta_mbps)s, %(upload_alerta_mbps)s,
                    %(cpu_alerta_pct)s, %(memoria_alerta_pct)s,
                    %(disco_alerta_pct)s, %(trafego_alerta_mbps)s,
                    %(snmp_community)s, %(snmp_port)s, %(agente_porta)s, %(agente_path)s)
            """,
            data,
        )
        device_id = int(cur.lastrowid)
        conn.commit()
    except mysql.connector.IntegrityError:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"erro": "este host e porta já estão cadastrados"}), 409
    cur.close()
    conn.close()
    return jsonify({"id": device_id}), 201


@app.route("/apps/tecnologia/api/devices/<int:device_id>", methods=["PUT", "DELETE"])
@login_required
def tecnologia_device_api(device_id):
    denied = technology_admin_or_error()
    if denied:
        return denied
    conn = get_conn()
    cur = conn.cursor()
    if request.method == "DELETE":
        cur.execute("DELETE FROM tecnologia_dispositivos WHERE id=%s", (device_id,))
        changed = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return ("", 204) if changed else (jsonify({"erro": "equipamento não encontrado"}), 404)
    payload = request.get_json(silent=True) or {}
    cur.execute("SELECT snmp_community FROM tecnologia_dispositivos WHERE id=%s", (device_id,))
    existing = cur.fetchone()
    if not existing:
        cur.close()
        conn.close()
        return jsonify({"erro": "equipamento não encontrado"}), 404
    existing_community = str(existing[0] or "")
    if not str(payload.get("snmpCommunity") or "").strip() and existing_community:
        payload["preserveSnmpCommunity"] = True
    try:
        data = normalize_device_payload(payload)
    except (TypeError, ValueError) as exc:
        cur.close()
        conn.close()
        return jsonify({"erro": str(exc)}), 400
    if not data.get("snmp_community") and existing_community:
        data["snmp_community"] = existing_community
    data["id"] = device_id
    conflict = technology_device_address_conflict(
        data, get_technology_devices(), exclude_device_id=device_id
    )
    if conflict:
        host, registered = conflict
        cur.close()
        conn.close()
        return jsonify({
            "erro": f"o endereço {host} já pertence a {registered.get('nome') or registered.get('host')}"
        }), 409
    try:
        cur.execute(
            """
            UPDATE tecnologia_dispositivos
            SET nome=%(nome)s, tipo=%(tipo)s, host=%(host)s,
                enderecos_adicionais=%(enderecos_adicionais)s, porta=%(porta)s,
                sonda=%(sonda)s, localizacao=%(localizacao)s,
                observacoes=%(observacoes)s, critico=%(critico)s,
                ativo=%(ativo)s, latencia_alerta_ms=%(latencia_alerta_ms)s,
                perda_alerta_pct=%(perda_alerta_pct)s,
                download_alerta_mbps=%(download_alerta_mbps)s,
                upload_alerta_mbps=%(upload_alerta_mbps)s,
                cpu_alerta_pct=%(cpu_alerta_pct)s,
                memoria_alerta_pct=%(memoria_alerta_pct)s,
                disco_alerta_pct=%(disco_alerta_pct)s,
                trafego_alerta_mbps=%(trafego_alerta_mbps)s,
                snmp_community=%(snmp_community)s, snmp_port=%(snmp_port)s,
                agente_porta=%(agente_porta)s, agente_path=%(agente_path)s
            WHERE id=%(id)s
            """,
            data,
        )
        changed = cur.rowcount
        conn.commit()
    except mysql.connector.IntegrityError:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"erro": "este host e porta já estão cadastrados"}), 409
    cur.close()
    conn.close()
    return jsonify({"ok": True, "changed": bool(changed)})


@app.route("/apps/tecnologia/api/discover-printers", methods=["POST"])
@login_required
def tecnologia_discover_printers_api():
    denied = technology_admin_or_error()
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    try:
        discovered = discover_printers(payload.get("subnet") or "192.168.200.0/24")
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    existing = technology_registered_device_hosts(get_technology_devices())
    available = []
    ignored = []
    for item in discovered:
        registered_name = existing.get(item["host"])
        if registered_name:
            ignored.append({"host": item["host"], "registeredName": registered_name})
        else:
            available.append(item)
    return jsonify({
        "devices": available,
        "ignoredRegistered": len(ignored),
        "ignoredDevices": ignored,
    })


@app.route("/apps/tecnologia/api/discover-computers", methods=["POST"])
@login_required
def tecnologia_discover_computers_api():
    denied = technology_admin_or_error()
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    try:
        discovered = discover_computers(payload.get("subnet") or "192.168.200.0/24")
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    existing = technology_registered_device_index(get_technology_devices())
    for item in discovered:
        registered = technology_registered_device_match(
            existing, host=item.get("host"), identity_name=item.get("name")
        )
        item["registered"] = bool(registered)
        item["registeredName"] = registered.get("nome") if registered else ""
        item["registeredType"] = registered.get("tipo") if registered else ""
    return jsonify({"devices": discovered})


@app.route("/apps/tecnologia")
@login_required
def tecnologia_static_root():
    start_technology_monitor()
    return static_app_response("tecnologia")


@app.route("/apps/tecnologia/original")
@login_required
def tecnologia_original_root():
    start_technology_monitor()
    return static_app_response("tecnologia", integrated=False)


@app.route("/apps/tecnologia/original/<path:subpath>")
@login_required
def tecnologia_original_static(subpath):
    return static_app_response("tecnologia", subpath, integrated=False)


@app.route("/apps/tecnologia/<path:subpath>")
@login_required
def tecnologia_static(subpath):
    return static_app_response("tecnologia", subpath)


# ---------------------------------------------------------------------------
# Integracao do app Financeiro
# ---------------------------------------------------------------------------
def default_finance_state():
    return {
        "contas": [
            {"id": "conta_principal", "nome": "Conta principal", "moeda": "BRL", "saldoInicial": 0}
        ],
        "categorias": [
            {"id": "cat_alimentacao", "nome": "Alimentação", "tipo": "DESPESA"},
            {"id": "cat_transporte", "nome": "Transporte", "tipo": "DESPESA"},
            {"id": "cat_moradia", "nome": "Moradia", "tipo": "DESPESA"},
            {"id": "cat_salario", "nome": "Salário", "tipo": "RECEITA"},
            {"id": "cat_outros", "nome": "Outros", "tipo": "DESPESA"},
        ],
        "lancamentos": [],
        "imports": [],
        "reconciliations": [],
        "ignoredBankTransactions": [],
        "favorecidos": [],
        "titulos": [],
        "compras": [],
        "config": {"tolDias": 3, "tolValor": 0.5, "scoreMin": 60},
    }


def normalize_finance_state(data):
    state = default_finance_state()
    if isinstance(data, dict):
        for collection in FINANCEIRO_COLLECTIONS:
            value = data.get(collection)
            state[collection] = value if isinstance(value, list) else []
        config = data.get("config")
        if isinstance(config, dict):
            state["config"].update(config)
    return state


def finance_state_revision(state):
    canonical = json.dumps(
        state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def record_id(collection, item, fallback_index):
    if isinstance(item, dict):
        for key in ("id", "bankTxId", "lancId"):
            if item.get(key):
                return str(item[key])
    return f"{collection}_{fallback_index}"


def get_finance_state():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    state = {
        "contas": [],
        "categorias": [],
        "lancamentos": [],
        "imports": [],
        "reconciliations": [],
        "ignoredBankTransactions": [],
        "favorecidos": [],
        "titulos": [],
        "compras": [],
        "config": {"tolDias": 3, "tolValor": 0.5, "scoreMin": 60},
    }
    cur.execute("SELECT payload FROM financeiro_config WHERE id=1")
    row = cur.fetchone()
    if row and row.get("payload"):
        payload = row["payload"]
        state["config"] = json.loads(payload) if isinstance(payload, str) else payload
    cur.execute("SELECT colecao, payload FROM financeiro_registros ORDER BY id")
    for row in cur.fetchall():
        collection = row["colecao"]
        if collection not in state:
            continue
        payload = row["payload"]
        state[collection].append(json.loads(payload) if isinstance(payload, str) else payload)
    cur.close()
    conn.close()
    if not any(state[collection] for collection in FINANCEIRO_COLLECTIONS):
        return default_finance_state()
    return normalize_finance_state(state)


def save_finance_state(data):
    state = normalize_finance_state(data)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM financeiro_registros")
    for collection in FINANCEIRO_COLLECTIONS:
        for index, item in enumerate(state[collection]):
            cur.execute(
                """
                INSERT INTO financeiro_registros (colecao, registro_id, payload)
                VALUES (%s, %s, %s)
                """,
                (collection, record_id(collection, item, index), json.dumps(item, ensure_ascii=False)),
            )
    cur.execute(
        """
        INSERT INTO financeiro_config (id, payload)
        VALUES (1, %s)
        ON DUPLICATE KEY UPDATE payload=VALUES(payload)
        """,
        (json.dumps(state["config"], ensure_ascii=False),),
    )
    conn.commit()
    cur.close()
    conn.close()
    return state


def finance_view_from_request():
    view = (request.args.get("view") or "dashboard").strip()
    return view if view in FINANCEIRO_VIEWS else "dashboard"


def set_finance_initial_view(markup, active_view):
    def replace(match):
        classes = match.group(1).split()
        view = match.group(2)
        classes = [item for item in classes if item != "hidden"]
        if view != active_view:
            classes.append("hidden")
        return f'<section class="{" ".join(classes)}" id="view-{view}">'

    return re.sub(
        r'<section class="([^"]*\bview\b[^"]*)" id="view-([^"]+)">',
        replace,
        markup,
        flags=re.I,
    )


def extract_finance_content(active_view="dashboard"):
    source = (FINANCEIRO_DIR / "source.html").read_text(encoding="utf-8", errors="replace")
    source = set_finance_initial_view(source, active_view)
    main = re.search(r'<main class="container">(.*?)</main>', source, flags=re.I | re.S)
    footer = re.search(r'<footer class="footer">(.*?)</footer>', source, flags=re.I | re.S)
    app_js_version = (FINANCEIRO_STATIC_DIR / "app.js").stat().st_mtime_ns
    parts = [
        '<div class="financeiro-app">',
        f'<main class="container">{main.group(1)}</main>' if main else source,
        f'<footer class="footer">{footer.group(1)}</footer>' if footer else "",
        "</div>",
        f'<script src="/apps/financeiro/static/app.js?v={app_js_version}"></script>',
    ]
    return "\n".join(parts)


@app.route("/apps/financeiro")
@login_required
def financeiro_page():
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"erro": "acesso negado"}), 403
    active_view = finance_view_from_request()
    finance_content = (
        "<script>"
        f"window.FINANCEIRO_ALLOWED = {json.dumps(allowed_resources_for_app(usuario, 'financeiro'))};"
        f"window.FINANCEIRO_INITIAL_VIEW = {json.dumps(active_view)};"
        "</script>"
        + extract_finance_content(active_view)
    )
    return render_template(
        "integrated_app.html",
        active_page=FINANCEIRO_ACTIVE_PAGES.get(active_view, "dashboards"),
        app_nome="Financeiro",
        app_style="",
        app_content=finance_content,
        **portal_context(usuario),
    )


@app.route("/apps/financeiro/original")
@login_required
def financeiro_original_page():
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"erro": "acesso negado"}), 403
    source = (FINANCEIRO_DIR / "source.html").read_text(encoding="utf-8", errors="replace")
    source = source.replace('href="styles.css"', 'href="/apps/financeiro/static/styles.css"')
    source = source.replace('<script src="../shared/remote-store.js"></script>', "")
    app_js_version = (FINANCEIRO_STATIC_DIR / "app.js").stat().st_mtime_ns
    source = source.replace(
        '<script src="app.js"></script>',
        (
            "<script>"
            f"window.FINANCEIRO_ALLOWED = {json.dumps(allowed_resources_for_app(usuario, 'financeiro'))};"
            "</script>"
            f'<script src="/apps/financeiro/static/app.js?v={app_js_version}"></script>'
        ),
    )
    source = apply_standalone_theme(source)
    return Response(source, content_type="text/html; charset=utf-8")


@app.route("/apps/financeiro/static/<path:filename>")
@login_required
def financeiro_static(filename):
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"erro": "acesso negado"}), 403
    response = send_from_directory(FINANCEIRO_STATIC_DIR, filename)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/apps/financeiro/api/state", methods=["GET", "PUT"])
@login_required
def financeiro_state_api():
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"erro": "acesso negado"}), 403
    if request.method == "GET":
        state = get_finance_state()
        revision = finance_state_revision(state)
        if request.args.get("revision") == revision:
            return jsonify({"ok": True, "changed": False, "revision": revision})
        return jsonify({"ok": True, "changed": True, "revision": revision, "state": state})
    data = request.get_json(silent=True) or {}
    expected_revision = str(data.get("revision") or "").strip()
    if not expected_revision:
        return jsonify({
            "error": "Atualize a tela antes de salvar os dados financeiros.",
            "code": "finance_revision_required",
        }), 428
    with _finance_state_lock:
        current_state = get_finance_state()
        current_revision = finance_state_revision(current_state)
        if expected_revision != current_revision:
            return jsonify({
                "error": "Os dados financeiros foram atualizados em outra aba.",
                "code": "finance_revision_conflict",
                "currentRevision": current_revision,
            }), 409
        state = save_finance_state(data.get("state") or {})
    return jsonify({
        "ok": True,
        "changed": True,
        "revision": finance_state_revision(state),
        "state": state,
    })


@app.route("/apps/financeiro/api/titles-report-pdf", methods=["POST"])
@login_required
def financeiro_titles_report_pdf_api():
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"error": "Acesso negado."}), 403

    data = request.get_json(silent=True) or {}
    report_type = str(data.get("tipo") or "").upper()
    required_resource = {"AP": "pagar", "AR": "receber"}.get(report_type)
    if not required_resource:
        return jsonify({"error": "Tipo de relatório inválido."}), 400

    allowed = allowed_resources_for_app(usuario, "financeiro")
    if "*" not in allowed and required_resource not in allowed:
        return jsonify({"error": "Acesso negado a este relatório."}), 403

    raw_ids = data.get("tituloIds")
    if not isinstance(raw_ids, list):
        return jsonify({"error": "Informe as contas que devem compor o relatório."}), 400
    title_ids = list(dict.fromkeys(
        str(title_id).strip() for title_id in raw_ids if str(title_id).strip()
    ))
    if len(title_ids) > 2000:
        return jsonify({"error": "O relatório excede o limite de 2000 contas. Reduza o filtro."}), 413

    state = get_finance_state()
    expected_revision = str(data.get("revision") or "").strip()
    if expected_revision != finance_state_revision(state):
        return jsonify({
            "error": "Os dados financeiros foram atualizados. Aguarde a sincronização e gere o relatório novamente."
        }), 409
    title_by_id = {
        str(title.get("id")): title
        for title in state.get("titulos", [])
        if isinstance(title, dict) and title.get("id") and title.get("tipo") == report_type
    }
    if any(title_id not in title_by_id for title_id in title_ids):
        return jsonify({
            "error": "As contas foram atualizadas. Atualize a tela e gere o relatório novamente."
        }), 409
    titles = [title_by_id[title_id] for title_id in title_ids]

    raw_filters = data.get("filtros") if isinstance(data.get("filtros"), list) else []
    filters = []
    for item in raw_filters[:8]:
        if not isinstance(item, dict):
            continue
        filters.append((str(item.get("label") or "")[:60], str(item.get("value") or "")[:180]))

    try:
        output, attachment_count = build_finance_titles_pdf(
            state,
            titles,
            report_type,
            filters,
            FINANCEIRO_ATTACHMENTS_DIR,
        )
    except FinancePdfReportError as exc:
        return jsonify({"error": str(exc)}), 422
    except RuntimeError:
        app.logger.exception("Dependências indisponíveis para gerar o relatório financeiro")
        return jsonify({"error": "O servidor não está preparado para gerar o PDF."}), 503
    except Exception:
        app.logger.exception("Falha ao gerar relatório financeiro em PDF")
        return jsonify({"error": "Não foi possível gerar o relatório em PDF."}), 500

    filename = (
        "contas-a-pagar" if report_type == "AP" else "contas-a-receber"
    ) + f"_{dt.date.today().isoformat()}.pdf"
    response = send_file(
        output,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=filename,
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Finance-Pdf-Attachments"] = str(attachment_count)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/apps/financeiro/api/import-pdf", methods=["POST"])
@login_required
def financeiro_import_pdf_api():
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"erro": "acesso negado"}), 403

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Selecione um arquivo PDF."}), 400
    if Path(secure_filename(upload.filename)).suffix.lower() != ".pdf":
        return jsonify({"error": "O arquivo deve estar no formato PDF."}), 400

    raw = upload.stream.read(MAX_FINANCE_PDF_BYTES + 1)
    if len(raw) > MAX_FINANCE_PDF_BYTES:
        return jsonify({"error": "O PDF excede o limite de 15 MB."}), 413
    if not raw.startswith(b"%PDF-"):
        return jsonify({"error": "O arquivo enviado não é um PDF válido."}), 400

    try:
        with tempfile.TemporaryDirectory(prefix="financeiro-upload-") as temp_dir:
            pdf_path = Path(temp_dir) / "extrato.pdf"
            pdf_path.write_bytes(raw)
            parsed = extract_bank_statement_pdf(pdf_path)
    except FinancePdfImportError as exc:
        return jsonify({"error": str(exc)}), 422

    return jsonify({"ok": True, **parsed})


@app.route("/apps/financeiro/api/import-installments-pdf", methods=["POST"])
@login_required
def financeiro_import_installments_pdf_api():
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"error": "Acesso negado."}), 403

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Selecione o PDF com as parcelas."}), 400
    if Path(secure_filename(upload.filename)).suffix.lower() != ".pdf":
        return jsonify({"error": "O arquivo deve estar no formato PDF."}), 400

    raw = upload.stream.read(MAX_FINANCE_PDF_BYTES + 1)
    if len(raw) > MAX_FINANCE_PDF_BYTES:
        return jsonify({"error": "O PDF excede o limite de 15 MB."}), 413
    if not raw.startswith(b"%PDF-"):
        return jsonify({"error": "O arquivo enviado não é um PDF válido."}), 400

    try:
        with tempfile.TemporaryDirectory(prefix="financeiro-parcelas-upload-") as temp_dir:
            pdf_path = Path(temp_dir) / "parcelas.pdf"
            pdf_path.write_bytes(raw)
            parsed = extract_installment_pdf(pdf_path)
    except FinancePdfImportError as exc:
        return jsonify({"error": str(exc)}), 422

    return jsonify({"ok": True, **parsed})


@app.route("/api/finance/reminders/run", methods=["POST"])
@login_required
def finance_reminders_run():
    return jsonify({"ok": True, "message": "Avisos financeiros ainda nao configurados neste portal."})


@app.route("/api/finance/ai-status")
@login_required
def finance_ai_status():
    return jsonify({
        "ok": True,
        "status": "disabled",
        "message": "Pesquisa financeira ainda nao configurada neste portal.",
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "details": [],
    })


@app.route("/api/finance/purchase-research", methods=["POST"])
@login_required
def finance_purchase_research():
    return jsonify({"error": "Pesquisa de compras ainda nao configurada neste portal."}), 501


@app.route("/api/finance/attachments", methods=["GET", "POST", "DELETE"])
@login_required
def finance_attachments():
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"error": "Acesso negado."}), 403

    def requested_attachment_name():
        value = str(request.args.get("path") or "").strip()
        if not value or Path(value).name != value or secure_filename(value) != value:
            return ""
        return value

    if request.method == "GET":
        filename = requested_attachment_name()
        if not filename:
            return jsonify({"error": "Anexo inválido."}), 400
        response = send_from_directory(FINANCEIRO_ATTACHMENTS_DIR, filename, conditional=True)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    if request.method == "DELETE":
        filename = requested_attachment_name()
        if not filename:
            return jsonify({"error": "Anexo inválido."}), 400
        attachment_path = FINANCEIRO_ATTACHMENTS_DIR / filename
        try:
            attachment_path.unlink(missing_ok=True)
        except OSError:
            return jsonify({"error": "Não foi possível remover o anexo."}), 500
        return ("", 204)

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Selecione um PDF ou imagem."}), 400
    original_name = secure_filename(upload.filename)
    suffix = Path(original_name).suffix.lower()
    allowed_suffixes = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
    if suffix not in allowed_suffixes:
        return jsonify({"error": "Formato permitido: PDF, PNG, JPG, WEBP ou GIF."}), 400

    raw = upload.stream.read(MAX_FINANCE_ATTACHMENT_BYTES + 1)
    if len(raw) > MAX_FINANCE_ATTACHMENT_BYTES:
        return jsonify({"error": "O anexo excede o limite de 15 MB."}), 413
    valid_magic = (
        (suffix == ".pdf" and raw.startswith(b"%PDF-"))
        or (suffix == ".png" and raw.startswith(b"\x89PNG\r\n\x1a\n"))
        or (suffix in {".jpg", ".jpeg"} and raw.startswith(b"\xff\xd8\xff"))
        or (suffix == ".webp" and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
        or (suffix == ".gif" and raw.startswith((b"GIF87a", b"GIF89a")))
    )
    if not valid_magic:
        return jsonify({"error": "O conteúdo do anexo não corresponde ao formato informado."}), 400

    attachment_id = secure_filename(request.form.get("attachmentId") or "")
    if not attachment_id:
        attachment_id = hashlib.sha256(raw).hexdigest()[:24]
    filename = f"{attachment_id}-{hashlib.sha256(raw).hexdigest()[:16]}{suffix}"
    FINANCEIRO_ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    (FINANCEIRO_ATTACHMENTS_DIR / filename).write_bytes(raw)
    mime = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    return jsonify({
        "attachment": {
            "id": attachment_id,
            "name": original_name,
            "mime": mime,
            "size": len(raw),
            "path": filename,
            "url": url_for("finance_attachments", path=filename),
        }
    })


def _finance_attachment_pdf_from_request():
    filename = str(request.args.get("path") or "").strip()
    if not filename or Path(filename).name != filename or secure_filename(filename) != filename:
        return None
    attachment_path = FINANCEIRO_ATTACHMENTS_DIR / filename
    if attachment_path.suffix.lower() != ".pdf" or not attachment_path.is_file():
        return None
    return attachment_path


@app.route("/api/finance/attachments/payment-code-info")
@login_required
def finance_attachment_payment_code_info():
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"error": "Acesso negado."}), 403
    attachment_path = _finance_attachment_pdf_from_request()
    if attachment_path is None:
        return jsonify({"error": "PDF não encontrado."}), 404
    try:
        page = max(1, min(60, int(request.args.get("page") or 1)))
        region = max(1, min(10, int(request.args.get("region") or 1)))
        items = extract_installment_pdf_page(attachment_path, page)
        item = items[min(region - 1, len(items) - 1)] if items else None
    except (ValueError, FinancePdfImportError) as exc:
        return jsonify({"error": str(exc)}), 422
    if not item:
        return jsonify({"error": "Código de pagamento não reconhecido nesta página."}), 422
    return jsonify({"ok": True, "payment": item})


@app.route("/api/finance/attachments/payment-code-image")
@login_required
def finance_attachment_payment_code_image():
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"error": "Acesso negado."}), 403
    attachment_path = _finance_attachment_pdf_from_request()
    if attachment_path is None:
        return jsonify({"error": "PDF não encontrado."}), 404
    try:
        page = max(1, min(60, int(request.args.get("page") or 1)))
        region = max(1, min(10, int(request.args.get("region") or 1)))
        regions = max(region, min(10, int(request.args.get("regions") or 1)))
    except ValueError:
        return jsonify({"error": "Página ou região inválida."}), 400
    kind = "qr" if request.args.get("kind") == "qr" else "barcode"

    try:
        from PIL import Image, ImageOps
        with tempfile.TemporaryDirectory(prefix="financeiro-codigo-") as temp_dir:
            prefix = Path(temp_dir) / "page"
            subprocess.run(
                [
                    "pdftoppm", "-f", str(page), "-l", str(page), "-singlefile",
                    "-r", "240", "-png", str(attachment_path), str(prefix),
                ],
                check=True, capture_output=True, timeout=45,
            )
            with Image.open(str(prefix) + ".png") as source:
                image = source.convert("RGB")
                width, height = image.size
                region_height = height / regions
                top = (region - 1) * region_height
                if kind == "qr":
                    crop_box = (
                        int(width * 0.58), int(top + region_height * 0.36),
                        int(width * 0.77), int(top + region_height * 0.68),
                    )
                else:
                    crop_box = (
                        int(width * 0.19), int(top + region_height * 0.76),
                        int(width * 0.79), int(top + region_height * 0.97),
                    )
                cropped = ImageOps.expand(image.crop(crop_box), border=24, fill="white")
                output = BytesIO()
                cropped.save(output, format="PNG", optimize=True)
                output.seek(0)
    except (OSError, subprocess.SubprocessError):
        return jsonify({"error": "Não foi possível gerar a imagem do código."}), 500
    return send_file(output, mimetype="image/png", max_age=0)


@app.route("/api/finance/pix-code", methods=["POST"])
@login_required
def finance_pix_code():
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"error": "Acesso negado."}), 403
    data = request.get_json(silent=True) or {}
    try:
        pix = build_static_pix_payload(
            key=data.get("key"),
            key_type=data.get("keyType"),
            amount=data.get("amount"),
            merchant_name=data.get("merchantName"),
            merchant_city=data.get("merchantCity"),
        )
        import qrcode

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(pix["payload"])
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        output = BytesIO()
        image.save(output, format="PNG")
        image_data = base64.b64encode(output.getvalue()).decode("ascii")
    except PixPayloadError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception:
        app.logger.exception("Falha ao gerar QR Code Pix")
        return jsonify({"error": "Não foi possível gerar o QR Code Pix."}), 500

    return jsonify({
        "ok": True,
        **pix,
        "image": f"data:image/png;base64,{image_data}",
    })


@app.route("/api/finance/attachments/decode", methods=["POST"])
@login_required
def finance_attachment_decode():
    return jsonify({"ok": False, "message": "Leitura de anexos ainda nao configurada neste portal."})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    login = str(data.get("login") or "").strip()
    senha = str(data.get("senha") or "").strip()
    if not login or not senha:
        return jsonify({"erro": "login e senha sao obrigatorios"}), 400

    row = get_user_by_login(login)
    if not row:
        return jsonify({"erro": "credenciais invalidas"}), 401
    if int(row.get("ativo") or 0) != 1:
        return jsonify({"erro": "usuario inativo"}), 403

    senha_db = str(row.get("senha") or "")
    senha_ok = False
    try:
        senha_ok = check_password_hash(senha_db, senha)
    except Exception:
        senha_ok = False

    if not senha_ok and senha_db == senha:
        senha_ok = True
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE usuarios SET senha=%s WHERE id=%s",
            (generate_password_hash(senha), row["id"]),
        )
        conn.commit()
        cur.close()
        conn.close()

    if not senha_ok:
        return jsonify({"erro": "credenciais invalidas"}), 401

    session["usuario_id"] = int(row["id"])
    session["usuario_login"] = row["login"]
    return jsonify({"ok": True, "usuario": public_user(row)})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
@login_required
def api_me():
    row = get_user_by_id(session["usuario_id"])
    if not row:
        return jsonify({"erro": "usuario nao encontrado"}), 404
    return jsonify({"ok": True, "usuario": public_user(row)})


@app.route("/api/apps")
@login_required
def api_apps():
    usuario = current_user_or_logout()
    if not usuario:
        return jsonify({"erro": "usuario nao encontrado"}), 404
    return jsonify({"ok": True, "apps": visible_apps_for_user(usuario)})


@app.route("/api/clientes-modulos")
@login_required
def api_client_contracts():
    return jsonify({"ok": True, **client_contracts_payload()})


@app.route("/api/clientes-modulos/ativo")
@login_required
def api_active_client_contract():
    payload = client_contracts_payload()
    if payload["configuredClientMissing"]:
        return jsonify({"erro": "CLIENTE_DEPLOY_ID nao corresponde a nenhum cliente cadastrado"}), 404
    if not payload["activeClient"]:
        return jsonify({"erro": "nenhum cliente ativo encontrado"}), 404
    return jsonify(
        {
            "ok": True,
            "client": payload["activeClient"],
            "activeClientId": payload["activeClientId"],
            "configuredClientId": payload["configuredClientId"],
            "selectedByEnv": payload["selectedByEnv"],
            "updatedAt": payload["updatedAt"],
        }
    )


@app.route("/api/clientes-modulos/clientes", methods=["POST"])
@login_required
def api_create_client_contract():
    _, error = current_admin_or_json_error()
    if error:
        return error
    try:
        create_client_contract(request.get_json(silent=True) or {})
        return jsonify({"ok": True, **client_contracts_payload()}), 201
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400


@app.route("/api/clientes-modulos/clientes/<client_id>", methods=["PUT"])
@login_required
def api_update_client_contract(client_id):
    _, error = current_admin_or_json_error()
    if error:
        return error
    try:
        update_client_contract(client_id, request.get_json(silent=True) or {})
        return jsonify({"ok": True, **client_contracts_payload()})
    except LookupError as exc:
        return jsonify({"erro": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400


@app.route("/api/clientes-modulos/clientes/<client_id>", methods=["DELETE"])
@login_required
def api_delete_client_contract(client_id):
    _, error = current_admin_or_json_error()
    if error:
        return error
    try:
        delete_client_contract(client_id)
        return jsonify({"ok": True, **client_contracts_payload()})
    except LookupError as exc:
        return jsonify({"erro": str(exc)}), 404


@app.route("/api/config/theme", methods=["POST"])
@login_required
def api_config_theme():
    data = request.get_json(silent=True) or {}
    tema = set_theme(str(data.get("tema") or "rio_branco").strip())
    return jsonify({"ok": True, "tema": tema})


@app.errorhandler(mysql.connector.Error)
def db_error(exc):
    status = 500
    detail = str(exc)
    if getattr(exc, "errno", None) == errorcode.ER_ACCESS_DENIED_ERROR:
        detail = "Acesso negado ao MySQL. Confira NS_DB_USER e NS_DB_PASSWORD."
    elif render_db_env_missing():
        detail = (
            "O app esta rodando no Render, mas as variaveis NS_DB_HOST/NS_DB_PORT "
            "nao foram aplicadas. Crie ou sincronize o Blueprint render.yaml na "
            "branch main, ou configure manualmente NS_DB_HOST, NS_DB_PORT, "
            "NS_DB_USER, NS_DB_PASSWORD e NS_DB_NAME no web service."
        )
    return render_template("db_error.html", detalhe=detail), status


warmup_render_riob()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("NS_HOST", "0.0.0.0"),
        port=int(os.environ.get("NS_PORT") or os.environ.get("PORT", "5600")),
        debug=as_bool(os.environ.get("NS_DEBUG"), True),
    )
