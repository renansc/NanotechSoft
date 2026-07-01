from functools import wraps
import html as html_lib
import json
import os
from pathlib import Path
import re
import mimetypes
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory, session, url_for
import mysql.connector
from mysql.connector import errorcode
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent


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


load_env_file(BASE_DIR / ".env")

APPS_DIR = BASE_DIR / "apps"
ALLOWED_APPS_FILE = BASE_DIR / "apps_liberados.txt"


def app_source_dir(app_key):
    return APPS_DIR / app_key / "source"


AUTOMACAO_DIR = Path(os.environ.get(
    "AUTOMACAO_APP_DIR",
    str(app_source_dir("automacao")),
))
FINANCEIRO_DIR = BASE_DIR / "apps" / "financeiro"
FINANCEIRO_STATIC_DIR = FINANCEIRO_DIR / "static"
NANOPONTO_DIR = Path(os.environ.get("NANOPONTO_APP_DIR", str(app_source_dir("nanoponto"))))
ZAP_DIR = Path(os.environ.get("ZAP_APP_DIR", str(app_source_dir("zap"))))
NANOSTORE_DIR = Path(os.environ.get("NANOSTORE_APP_DIR", str(app_source_dir("nanostore"))))
GPSMUSICAL_DIR = Path(os.environ.get("GPSMUSICAL_APP_DIR", str(app_source_dir("gpsmusical"))))
BPA_DIR = Path(os.environ.get("BPA_APP_DIR", str(app_source_dir("bpa"))))
TATOO_DIR = Path(os.environ.get("TATOO_APP_DIR", str(app_source_dir("tatoo"))))
NANOTECH_SHARED_DIR = Path(os.environ.get("NANOTECH_SHARED_DIR", str(APPS_DIR / "shared")))
FINANCEIRO_COLLECTIONS = ("contas", "categorias", "lancamentos", "imports", "reconciliations", "titulos", "compras")
FINANCEIRO_VIEWS = {
    "dashboard",
    "lancamentos",
    "contas",
    "categorias",
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
NANOPONTO_PORT = int(os.environ.get("NANOPONTO_PORT", "8891"))
NANOPONTO_BASE_URL = f"http://127.0.0.1:{NANOPONTO_PORT}"
ZAP_PORT = int(os.environ.get("ZAP_PORT", "8892"))
ZAP_BASE_URL = f"http://127.0.0.1:{ZAP_PORT}"
NANOSTORE_PORT = int(os.environ.get("NANOSTORE_PORT", "8893"))
NANOSTORE_BASE_URL = f"http://127.0.0.1:{NANOSTORE_PORT}"
RIOB_BASE_URL = os.environ.get("RIOB_BASE_URL", "http://127.0.0.1:8898").rstrip("/")
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
        "startup_wait": 180,
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
    "riob-email": {
        "cwd": APPS_DIR / "riob-email" / "source",
        "script": "gerenciador_email.py",
        "port": int(os.environ.get("RIOB_EMAIL_PORT", "8896")),
        "env": {
            "FLASK_RUN_HOST": "127.0.0.1",
            "FLASK_RUN_PORT": os.environ.get("RIOB_EMAIL_PORT", "8896"),
            "PORT": os.environ.get("RIOB_EMAIL_PORT", "8896"),
        },
    },
    "riob-xml": {
        "cwd": APPS_DIR / "riob-xml" / "source",
        "script": "importador_xml_homologacao.py",
        "port": int(os.environ.get("RIOB_XML_PORT", "8897")),
        "env": {
            "FLASK_RUN_HOST": "127.0.0.1",
            "FLASK_RUN_PORT": os.environ.get("RIOB_XML_PORT", "8897"),
            "PORT": os.environ.get("RIOB_XML_PORT", "8897"),
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
}

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
    conn.commit()
    cur.close()
    conn.close()
    _db_ready = True


@app.before_request
def bootstrap_request():
    if request.path.startswith("/static/") or request.path == "/healthz":
        return
    ensure_database()


@app.after_request
def add_no_cache_headers(resp):
    if request.path.startswith("/api/") or request.path in {"/", "/login", "/config"}:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


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
    }


def user_is_admin(usuario):
    return (usuario or {}).get("perfil") == "admin"


def get_user_by_login(login):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome, login, senha, perfil, ativo FROM usuarios WHERE login=%s LIMIT 1",
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
        "SELECT id, nome, login, perfil, ativo FROM usuarios WHERE id=%s LIMIT 1",
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


def menu_display_name(item, app_name):
    nome = str(item.get("nome") or "").strip()
    if not nome:
        return app_name
    if app_name.lower() in nome.lower():
        return nome
    return f"{nome} {app_name}"


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
    """Lê a allowlist de deploy: cada linha habilita um app no portal."""
    if not ALLOWED_APPS_FILE.exists():
        return None
    keys = set()
    for raw in ALLOWED_APPS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keys.add(line)
    return keys


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


def list_apps():
    allowed = allowed_app_keys()
    merged = {}
    for item in database_apps() + filesystem_apps():
        if item and item["ativo"] and (allowed is None or item["app_key"] in allowed):
            merged[item["app_key"]] = item
    return sorted(merged.values(), key=lambda x: (x["ordem"], x["nome"].lower()))


def app_visible_to_user(app_item, usuario):
    if user_is_admin(usuario):
        return True
    permissions = get_user_permissions(usuario).get(app_item["app_key"], set())
    return bool(permissions)


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
                            "nome": menu_display_name(item, app_item["nome"]),
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
                            "nome": menu_display_name(item, app_item["nome"]),
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
    user = get_user_by_id(session["usuario_id"])
    if not user or int(user.get("ativo") or 0) != 1:
        session.clear()
        return None
    return public_user(user)


def portal_context(usuario=None):
    usuario = usuario or current_user_or_logout()
    apps = list_apps()
    visible_apps = [app_item for app_item in apps if app_visible_to_user(app_item, usuario)]
    return {
        "usuario": usuario,
        "apps": visible_apps,
        "menu": menu_sections(apps, usuario),
        "config": get_config(),
        "themes": THEMES,
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
        '"/monitor/': f'"{prefix}/monitor/',
        "'/monitor/": f"'{prefix}/monitor/",
        '"/importar-xml/': f'"{prefix}/importar-xml/',
        "'/importar-xml/": f"'{prefix}/importar-xml/",
        '"/gestor-emails/': f'"{prefix}/gestor-emails/',
        "'/gestor-emails/": f"'{prefix}/gestor-emails/",
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
        '"/monitor/': f'"{prefix}/monitor/',
        "'/monitor/": f"'{prefix}/monitor/",
        '"/importar-xml/': f'"{prefix}/importar-xml/',
        "'/importar-xml/": f"'{prefix}/importar-xml/",
        '"/gestor-emails/': f'"{prefix}/gestor-emails/',
        "'/gestor-emails/": f"'{prefix}/gestor-emails/",
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


def local_riob_prefix(app_key):
    return f"/apps/{app_key}/riob"


def rewrite_local_riob_location(value, app_key):
    prefix = local_riob_prefix(app_key)
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme and parsed.netloc:
        return prefix + (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
    if value.startswith(prefix):
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
    headers["X-Forwarded-Prefix"] = f"/apps/{app_key}"
    data = request.get_data() if request.method in {"POST", "PUT", "PATCH"} else None
    req = urllib.request.Request(upstream_url, data=data, headers=headers, method=request.method)

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
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


def riob_proxy_response(app_key="riob", subpath=""):
    usuario = current_user_or_logout()
    if not usuario:
        return redirect(url_for("login_page"))
    if not app_visible_to_user({"app_key": app_key}, usuario):
        return jsonify({"erro": "app nao liberado para este usuario"}), 403

    route = riob_app_path(app_key, subpath)
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
    if "riob" in LOCAL_RIOB_APPS:
        if subpath == "riob" or subpath.startswith("riob/"):
            subpath = subpath[4:].lstrip("/")
        return local_riob_proxy_response("riob", subpath)
    return riob_proxy_response("riob", subpath)


@app.route("/apps/<app_key>/riob", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/apps/<app_key>/riob/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/apps/<app_key>/riob/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@login_required
def riob_module_proxy(app_key, subpath=""):
    if app_key in LOCAL_RIOB_APPS:
        return local_riob_proxy_response(app_key, subpath)
    if app_key in LOCAL_RIOB_ALIASES:
        target_key, fragment = LOCAL_RIOB_ALIASES[app_key]
        if subpath:
            return local_riob_proxy_response(target_key, subpath)
        return redirect(f"/apps/{target_key}/riob/{fragment}")
    if app_key not in RIOB_ROUTE_DEFAULTS:
        return jsonify({"erro": "modulo RioB nao encontrado"}), 404
    return riob_proxy_response(app_key, subpath)


@app.route("/apps/<app_key>")
@login_required
def app_placeholder(app_key):
    if app_key in LOCAL_RIOB_APPS:
        return local_riob_proxy_response(app_key, "")
    if app_key in LOCAL_RIOB_ALIASES:
        target_key, fragment = LOCAL_RIOB_ALIASES[app_key]
        return redirect(f"/apps/{target_key}/riob/{fragment}")
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
        for _ in range(30):
            if tcp_open("127.0.0.1", AUTOMACAO_PORT):
                _app_startup_errors.pop("automacao", None)
                return True
            time.sleep(0.2)
        log_app_startup_error("automacao", f"processo iniciou, mas a porta 127.0.0.1:{AUTOMACAO_PORT} nao respondeu")
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

    headers = {key: value for key, value in request.headers.items() if key.lower() not in {"host", "content-length", "connection"}}
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
# Integracao de apps estaticos Nanotech
# ---------------------------------------------------------------------------
STATIC_APP_DIRS = {
    "gpsmusical": GPSMUSICAL_DIR,
    "bpa": BPA_DIR,
    "tatoo": TATOO_DIR,
}

STATIC_APP_INDEX = {
    "gpsmusical": "index.html",
    "bpa": "index.html",
    "tatoo": "index.html",
}

STATIC_APP_NAMES = {
    "gpsmusical": "GPS Musical",
    "bpa": "BPA",
    "tatoo": "Tatoo",
}


def static_app_active_page(app_key, subpath):
    if app_key == "gpsmusical":
        return "dashboards"
    if app_key == "bpa":
        return "cadastros"
    if app_key == "tatoo":
        return "cadastros"
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
    parts = [
        '<div class="financeiro-app">',
        f'<main class="container">{main.group(1)}</main>' if main else source,
        f'<footer class="footer">{footer.group(1)}</footer>' if footer else "",
        "</div>",
        '<script src="/apps/financeiro/static/app.js"></script>',
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
    source = source.replace(
        '<script src="app.js"></script>',
        (
            "<script>"
            f"window.FINANCEIRO_ALLOWED = {json.dumps(allowed_resources_for_app(usuario, 'financeiro'))};"
            "</script>"
            '<script src="/apps/financeiro/static/app.js"></script>'
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
    return send_from_directory(FINANCEIRO_STATIC_DIR, filename)


@app.route("/apps/financeiro/api/state", methods=["GET", "PUT"])
@login_required
def financeiro_state_api():
    usuario = current_user_or_logout()
    if not app_visible_to_user({"app_key": "financeiro"}, usuario):
        return jsonify({"erro": "acesso negado"}), 403
    if request.method == "GET":
        return jsonify({"ok": True, "state": get_finance_state()})
    data = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "state": save_finance_state(data.get("state") or data)})


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


@app.route("/api/finance/attachments", methods=["POST", "DELETE"])
@login_required
def finance_attachments():
    if request.method == "DELETE":
        return ("", 204)
    return jsonify({"attachment": None, "message": "Anexos financeiros ainda nao configurados neste portal."})


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
    return jsonify({"ok": True, "apps": list_apps()})


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
    return render_template("db_error.html", detalhe=detail), status


if __name__ == "__main__":
    app.run(
        host=os.environ.get("NS_HOST", "0.0.0.0"),
        port=int(os.environ.get("NS_PORT") or os.environ.get("PORT", "5600")),
        debug=as_bool(os.environ.get("NS_DEBUG"), True),
    )
