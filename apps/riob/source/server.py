from flask import Flask, request, jsonify, send_from_directory, send_file, Response
import mysql.connector
import subprocess
import datetime
import base64
import csv
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
import html as html_lib
import shutil
import socket
import ssl
import sys
import time
import threading
import uuid
import hashlib
import mimetypes
import re
import xml.etree.ElementTree as ET
import zlib
from html.parser import HTMLParser
from urllib.parse import urlparse
import paramiko
import nfe_ws

app = Flask(__name__, static_folder='.')


def _load_env_file(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and os.environ.get(k) in (None, ""):
                    os.environ[k] = v
    except Exception:
        pass


# =========================================================
# (0.5) EVITAR CACHE DO NAVEGADOR NAS ROTAS /api
# (isso evita ver cadastros "antigos" depois de excluir/editar)
# =========================================================
@app.after_request
def add_no_cache_headers(resp):
    try:
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
    except Exception:
        pass
    return resp

# Limite de upload alinhado ao proxy para CSVs grandes e fotos de DANFE
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB

# =========================================================
# (0) ARQUIVOS / DIRETÓRIOS
# =========================================================
BASE_DIR = os.path.dirname(__file__)
DOCS_DIR = os.path.join(BASE_DIR, "docs")

# Carrega variaveis de ambiente automaticamente (sem export manual)
_load_env_file(os.path.join(BASE_DIR, ".env"))

DATA_ROOT = os.environ.get("RB_DATA_DIR", BASE_DIR)
FOTOS_DIR = os.path.join(DATA_ROOT, "FotosDevolucoes")
REQ_ABAST_DIR = os.path.join(DATA_ROOT, "RequisicoesAbastecimento")
CHAT_ATTACHMENTS_DIR = os.path.join(DATA_ROOT, "ChatAnexos")
NFE_XML_CACHE_DIR = os.path.join(DATA_ROOT, "nfe-cache")
NFE_DFE_LIMIT_FILE = os.path.join(DATA_ROOT, "nfe-dfe-limit.json")
VENDAS_RELATORIOS_DIR = os.path.join(BASE_DIR, "Relatorios")
VENDAS_CACHE_DIR = os.path.join(DATA_ROOT, "vendas-cache")
VENDAS_UPLOADS_DIR = os.path.join(VENDAS_CACHE_DIR, "uploads")
VENDAS_CACHE_INDEX_FILE = os.path.join(VENDAS_CACHE_DIR, "index.json")
VENDAS_CONFIG_FILE = os.path.join(DATA_ROOT, "vendas-config.json")
DB_BACKUP_DIR = os.environ.get("RB_DB_BACKUP_DIR", os.path.join(BASE_DIR, "backups sql"))
os.makedirs(DATA_ROOT, exist_ok=True)
os.makedirs(FOTOS_DIR, exist_ok=True)
os.makedirs(REQ_ABAST_DIR, exist_ok=True)
os.makedirs(CHAT_ATTACHMENTS_DIR, exist_ok=True)
os.makedirs(NFE_XML_CACHE_DIR, exist_ok=True)
os.makedirs(VENDAS_CACHE_DIR, exist_ok=True)
os.makedirs(VENDAS_UPLOADS_DIR, exist_ok=True)
try:
    os.makedirs(DB_BACKUP_DIR, exist_ok=True)
except Exception:
    pass

_monitor_lock = threading.Lock()
_monitor_procs = {}
_nfe_dfe_limit_lock = threading.Lock()
_rapidocr_lock = threading.Lock()
_rapidocr_engine = None
VSPHERE_CLIENT_DIR = os.environ.get("RB_VSPHERE_CLIENT_CONTAINER_PATH", "/opt/vsphere-flask-client")
_MONITOR_APPS = {
    "esxi": {
        "cwd": VSPHERE_CLIENT_DIR,
        "script": "app.py",
        "port": 5500,
        "env": {"FLASK_RUN_HOST": "127.0.0.1", "FLASK_RUN_PORT": "5500"},
    },
    "cameras": {
        "cwd": os.path.join(BASE_DIR, "cameras"),
        "script": "server.py",
        "port": 8889,
        "env": {"APP_HOST": "127.0.0.1"},
    },
}

def _tcp_open(host, port, timeout=0.5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False

def _ensure_monitor_app(name):
    cfg = _MONITOR_APPS.get(name)
    if not cfg:
        return False

    port = int(cfg["port"])
    if _tcp_open("127.0.0.1", port):
        return True

    with _monitor_lock:
        if _tcp_open("127.0.0.1", port):
            return True

        p = _monitor_procs.get(name)
        if p is not None and p.poll() is None:
            time.sleep(0.25)
            return _tcp_open("127.0.0.1", port)
        if p is not None and p.poll() is not None:
            _monitor_procs.pop(name, None)

        cwd = cfg.get("cwd") or BASE_DIR
        script = cfg.get("script") or "server.py"
        _load_env_file(os.path.join(BASE_DIR, ".env"))

        env = os.environ.copy()
        env.update(cfg.get("env") or {})
        if name == "esxi":
            env.update({
                "FLASK_SECRET_KEY": os.environ.get("FLASK_SECRET") or "troque-esta-chave-agora-123",
                "UI_USER": os.environ.get("UI_USER", ""),
                "UI_PASS": os.environ.get("UI_PASS", ""),
                "VSPHERE_AUTO_CONNECT": os.environ.get("VSPHERE_AUTO_CONNECT", "1"),
                "VSPHERE_DEFAULT_HOST": os.environ.get("VSPHERE_DEFAULT_HOST", os.environ.get("ESXI_HOST", "192.168.200.198")),
                "VSPHERE_DEFAULT_USERNAME": os.environ.get("VSPHERE_DEFAULT_USERNAME", os.environ.get("ESXI_USER", "root")),
                "VSPHERE_DEFAULT_PASSWORD": os.environ.get("VSPHERE_DEFAULT_PASSWORD", os.environ.get("ESXI_PASS", "")),
                "VSPHERE_DEFAULT_PORT": os.environ.get("VSPHERE_DEFAULT_PORT", os.environ.get("ESXI_VSPHERE_PORT", "443")),
                "VSPHERE_DEFAULT_VERIFY_SSL": os.environ.get("VSPHERE_DEFAULT_VERIFY_SSL", os.environ.get("ESXI_VERIFY_SSL", "0")),
            })

        try:
            proc = subprocess.Popen(
                [sys.executable, script],
                cwd=cwd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _monitor_procs[name] = proc
        except Exception:
            return False

    for _ in range(20):
        if _tcp_open("127.0.0.1", port):
            return True
        time.sleep(0.2)
    return False

def _ensure_monitor_apps():
    out = {}
    for name in _MONITOR_APPS.keys():
        cfg = _MONITOR_APPS[name]
        ok = _ensure_monitor_app(name)
        out[name] = {"running": bool(ok), "port": int(cfg["port"])}
    return out

def _proxy_monitor(name, subpath=""):
    cfg = _MONITOR_APPS.get(name)
    if not cfg:
        return jsonify({"ok": False, "erro": "app monitor invalido"}), 404

    if not _ensure_monitor_app(name):
        return jsonify({"ok": False, "erro": f"falha ao iniciar app {name}"}), 503

    port = int(cfg["port"])
    path = "/" + (subpath or "")
    if not path.startswith("/"):
        path = "/" + path
    qs = request.query_string.decode("utf-8", errors="ignore")
    if qs:
        path = f"{path}?{qs}"

    import urllib.request
    import urllib.error

    target = f"http://127.0.0.1:{port}{path}"
    body = request.get_data() if request.method in ("POST", "PUT", "PATCH", "DELETE") else None
    headers = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in ("host", "content-length", "connection", "accept-encoding"):
            continue
        headers[k] = v

    req = urllib.request.Request(target, data=body, headers=headers, method=request.method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            out = Response(payload, status=resp.status)
            for k, v in resp.headers.items():
                lk = k.lower()
                if lk in ("content-length", "transfer-encoding", "connection", "content-encoding"):
                    continue
                out.headers[k] = v
            return out
    except urllib.error.HTTPError as e:
        payload = e.read()
        out = Response(payload, status=e.code)
        for k, v in e.headers.items():
            lk = k.lower()
            if lk in ("content-length", "transfer-encoding", "connection", "content-encoding"):
                continue
            out.headers[k] = v
        return out
    except Exception as e:
        return jsonify({"ok": False, "erro": f"proxy {name} indisponivel", "detalhes": str(e)}), 502

# =========================================================
# (1) CONFIG DO BANCO (ENV VARS + FALLBACK)
# =========================================================
# Você pode definir no Linux/Windows:
#   export DB_HOST="..."
#   export DB_USER="..."
#   export DB_PASSWORD="..."
#   export DB_NAME="..."
#   export DB_PORT="3306"
#
# Se não definir, ele usa os valores atuais (fallback)

def _env(name, default=None):
    v = os.environ.get(name)
    return v if (v is not None and str(v).strip() != "") else default

def _env_int(name, default):
    v = os.environ.get(name)
    try:
        return int(v) if v is not None and str(v).strip() != "" else int(default)
    except:
        return int(default)

db_config = {
    "host": _env("DB_HOST", "127.0.0.1"),
    "user": _env("DB_USER", "root"),
    "password": _env("DB_PASSWORD", ""),
    "database": _env("DB_NAME", "riobranco"),
    "port": _env_int("DB_PORT", 3306),
}

def get_conn():
    return mysql.connector.connect(**db_config)

# =========================================================
# (1.5) MIGRAÇÃO / GARANTIR ESQUEMA (FROTA)
# =========================================================
def ensure_schema():
    """Cria/ajusta colunas/tabelas necessárias para Gestão de Frota."""
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()

        # 1) Novas colunas em veiculos para intervalos (se não existirem)
        # - intervalo_manut_km: quantos KM entre manutenções
        # - intervalo_oleo_km: quantos KM entre trocas de óleo
        try:
            cur.execute("ALTER TABLE veiculos ADD COLUMN intervalo_manut_km INT DEFAULT 10000")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE veiculos ADD COLUMN intervalo_oleo_km INT DEFAULT 5000")
        except Exception:
            pass

        # 2) Tabelas de histórico
        cur.execute("""
        CREATE TABLE IF NOT EXISTS manutencoes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            veiculo_id INT NOT NULL,
            tipo VARCHAR(120) DEFAULT '',
            km INT DEFAULT 0,
            valor DECIMAL(10,2) DEFAULT 0,
            data_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (veiculo_id),
            INDEX (km),
            INDEX (data_registro)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS trocas_oleo (
            id INT AUTO_INCREMENT PRIMARY KEY,
            veiculo_id INT NOT NULL,
            tipo VARCHAR(120) DEFAULT '',
            km INT DEFAULT 0,
            data_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (veiculo_id),
            INDEX (km),
            INDEX (data_registro)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS trocas_pneu (
            id INT AUTO_INCREMENT PRIMARY KEY,
            veiculo_id INT NOT NULL,
            data_troca DATE NULL,
            km INT DEFAULT 0,
            marca VARCHAR(120) DEFAULT '',
            valor_total DECIMAL(10,2) DEFAULT 0,
            quantidade INT DEFAULT 1,
            localizacao_posicao VARCHAR(60) DEFAULT '',
            localizacao_lado VARCHAR(60) DEFAULT '',
            localizacao VARCHAR(60) DEFAULT '',
            observacao_rodizio VARCHAR(255) DEFAULT '',
            data_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (veiculo_id),
            INDEX (km),
            INDEX (data_registro)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS abastecimentos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            veiculo_id INT NOT NULL,
            km INT DEFAULT 0,
            posto VARCHAR(160) DEFAULT '',
            combustivel_tipo VARCHAR(20) DEFAULT 'diesel',
            chave_acesso_nfe VARCHAR(64) DEFAULT '',
            numero_nota VARCHAR(120) DEFAULT '',
            emitente_nome VARCHAR(255) DEFAULT '',
            valor DECIMAL(10,2) NULL,
            quantidade_litros DECIMAL(10,3) NULL,
            status VARCHAR(30) DEFAULT 'liberado',
            data_liberacao DATETIME DEFAULT CURRENT_TIMESTAMP,
            data_abastecimento DATETIME NULL,
            INDEX (veiculo_id),
            INDEX (status),
            INDEX (km),
            INDEX (data_liberacao),
            INDEX (data_abastecimento)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS lavagens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            veiculo_id INT NOT NULL,
            data_lavagem DATE NULL,
            km INT DEFAULT 0,
            local VARCHAR(160) DEFAULT '',
            valor DECIMAL(10,2) DEFAULT 0,
            observacao VARCHAR(255) DEFAULT '',
            data_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (veiculo_id),
            INDEX (km),
            INDEX (data_lavagem),
            INDEX (data_registro)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS fretes_historico (
            id INT AUTO_INCREMENT PRIMARY KEY,
            frete_id INT NOT NULL,
            acao VARCHAR(40) NOT NULL,
            usuario VARCHAR(180) NOT NULL DEFAULT 'desconhecido',
            frete_nome VARCHAR(255) DEFAULT '',
            status_anterior VARCHAR(40) DEFAULT '',
            status_novo VARCHAR(40) DEFAULT '',
            veiculo_nome VARCHAR(180) DEFAULT '',
            motorista_nome VARCHAR(180) DEFAULT '',
            entregador_nome VARCHAR(180) DEFAULT '',
            detalhes VARCHAR(500) DEFAULT '',
            dados_antes_json LONGTEXT NULL,
            dados_depois_json LONGTEXT NULL,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (frete_id),
            INDEX (acao),
            INDEX (criado_em)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS estoque_movimentos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            codigo_barras VARCHAR(120) DEFAULT '',
            numero_nota VARCHAR(120) DEFAULT '',
            nome_produto VARCHAR(255) NOT NULL,
            quantidade DECIMAL(12,3) DEFAULT 0,
            valor_unitario DECIMAL(12,2) DEFAULT 0,
            tipo_movimento VARCHAR(20) DEFAULT 'entrada',
            origem_setor VARCHAR(80) DEFAULT '',
            destino_setor VARCHAR(80) DEFAULT '',
            referencia_tipo VARCHAR(60) DEFAULT '',
            referencia_id INT NULL,
            usuario_registro VARCHAR(180) DEFAULT '',
            data_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (codigo_barras),
            INDEX (numero_nota),
            INDEX (nome_produto),
            INDEX (tipo_movimento),
            INDEX (data_registro)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS estoque_produtos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            codigo_barras VARCHAR(120) DEFAULT '',
            codigo_produto_nfe VARCHAR(120) DEFAULT '',
            nome_produto VARCHAR(255) NOT NULL,
            unidade VARCHAR(30) DEFAULT '',
            embalagem_tipo_padrao VARCHAR(30) DEFAULT '',
            fator_embalagem_padrao DECIMAL(12,3) DEFAULT 0,
            origem_cadastro VARCHAR(40) DEFAULT 'manual',
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX (codigo_barras),
            INDEX (codigo_produto_nfe),
            INDEX (nome_produto)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS estoque_conferencias (
            id INT AUTO_INCREMENT PRIMARY KEY,
            numero_nota VARCHAR(120) DEFAULT '',
            chave_acesso VARCHAR(64) DEFAULT '',
            serie VARCHAR(30) DEFAULT '',
            emitente_nome VARCHAR(255) DEFAULT '',
            emitente_cnpj VARCHAR(32) DEFAULT '',
            destinatario_nome VARCHAR(255) DEFAULT '',
            destinatario_cnpj VARCHAR(32) DEFAULT '',
            data_emissao VARCHAR(40) DEFAULT '',
            status VARCHAR(30) DEFAULT 'pendente',
            origem_setor VARCHAR(80) DEFAULT 'Fabrica',
            destino_setor VARCHAR(80) DEFAULT 'Almoxarifado',
            arquivo_origem VARCHAR(255) DEFAULT '',
            recebido_por VARCHAR(180) DEFAULT '',
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            confirmado_em DATETIME NULL,
            INDEX (numero_nota),
            INDEX (chave_acesso),
            INDEX (status),
            INDEX (criado_em)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS estoque_conferencia_itens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            conferencia_id INT NOT NULL,
            item_seq VARCHAR(30) DEFAULT '',
            produto_id INT NULL,
            codigo_produto_nfe VARCHAR(120) DEFAULT '',
            codigo_barras VARCHAR(120) DEFAULT '',
            nome_produto VARCHAR(255) NOT NULL,
            unidade VARCHAR(30) DEFAULT '',
            embalagem_tipo VARCHAR(30) DEFAULT '',
            quantidade_embalagem DECIMAL(12,3) DEFAULT 0,
            fator_embalagem DECIMAL(12,3) DEFAULT 1,
            fator_inferido TINYINT(1) DEFAULT 0,
            quantidade_nfe DECIMAL(12,3) DEFAULT 0,
            quantidade_conferida DECIMAL(12,3) DEFAULT 0,
            valor_unitario DECIMAL(12,2) DEFAULT 0,
            estoque_movimento_id INT NULL,
            consolidado_em DATETIME NULL,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (conferencia_id),
            INDEX (produto_id),
            INDEX (codigo_barras),
            INDEX (nome_produto)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nome VARCHAR(120) NOT NULL,
            login VARCHAR(80) NOT NULL UNIQUE,
            senha VARCHAR(255) NOT NULL,
            ativo TINYINT(1) DEFAULT 1,
            sip_habilitado TINYINT(1) DEFAULT 0,
            sip_usuario VARCHAR(160) DEFAULT '',
            sip_senha VARCHAR(255) DEFAULT '',
            sip_ramal VARCHAR(160) DEFAULT '',
            codbar_modo VARCHAR(20) DEFAULT 'bip',
            data_cadastro DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (nome),
            INDEX (ativo),
            INDEX (sip_habilitado),
            INDEX (sip_ramal)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_mensagens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            remetente_id INT NOT NULL,
            destinatario_id INT NOT NULL,
            mensagem TEXT NOT NULL,
            anexo_nome VARCHAR(255) DEFAULT '',
            anexo_path VARCHAR(500) DEFAULT '',
            anexo_mime VARCHAR(160) DEFAULT '',
            anexo_tamanho BIGINT DEFAULT 0,
            lida TINYINT(1) DEFAULT 0,
            data_envio DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (remetente_id),
            INDEX (destinatario_id),
            INDEX (data_envio),
            CONSTRAINT fk_chat_remetente FOREIGN KEY (remetente_id) REFERENCES usuarios(id) ON DELETE CASCADE,
            CONSTRAINT fk_chat_destinatario FOREIGN KEY (destinatario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS logs_exclusoes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            usuario VARCHAR(180) NOT NULL DEFAULT 'desconhecido',
            entidade VARCHAR(80) NOT NULL,
            item_id INT NOT NULL DEFAULT 0,
            descricao VARCHAR(500) NOT NULL DEFAULT '',
            data_evento DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (data_evento),
            INDEX (entidade),
            INDEX (usuario)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sip_config (
            id INT PRIMARY KEY,
            habilitado TINYINT(1) DEFAULT 0,
            modo_ativo VARCHAR(30) DEFAULT 'freepbx',
            setevoip_config_json LONGTEXT NULL,
            freepbx_config_json LONGTEXT NULL,
            ws_url VARCHAR(255) DEFAULT '',
            dominio VARCHAR(180) DEFAULT '',
            registrar_server VARCHAR(255) DEFAULT '',
            outbound_proxy VARCHAR(255) DEFAULT '',
            prefixo_saida VARCHAR(40) DEFAULT '',
            caller_id_template VARCHAR(255) DEFAULT '{nome} RioBranco',
            stun_servers TEXT NULL,
            turn_url VARCHAR(255) DEFAULT '',
            turn_usuario VARCHAR(120) DEFAULT '',
            turn_senha VARCHAR(255) DEFAULT '',
            auto_register TINYINT(1) DEFAULT 1,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)
        cur.execute("INSERT IGNORE INTO sip_config (id) VALUES (1)")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS nfe_config (
            id INT PRIMARY KEY,
            habilitado TINYINT(1) DEFAULT 0,
            modo_ativo VARCHAR(30) DEFAULT 'portal_assistido',
            ambiente VARCHAR(20) DEFAULT 'producao',
            consulta_url VARCHAR(255) DEFAULT 'https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=completa&tipoConteudo=XbSeqxE8pl8=',
            abrir_portal_ao_bipar TINYINT(1) DEFAULT 1,
            bloquear_notas_duplicadas TINYINT(1) DEFAULT 1,
            destinatario_cnpj VARCHAR(18) DEFAULT '',
            uf_autor VARCHAR(2) DEFAULT '',
            certificado_arquivo VARCHAR(255) DEFAULT '',
            certificado_senha VARCHAR(255) DEFAULT '',
            ultimo_nsu VARCHAR(20) DEFAULT '',
            auto_manifestar_ciencia TINYINT(1) DEFAULT 1,
            azure_docint_habilitado TINYINT(1) DEFAULT 0,
            azure_docint_endpoint VARCHAR(255) DEFAULT '',
            azure_docint_key VARCHAR(255) DEFAULT '',
            azure_docint_model_id VARCHAR(120) DEFAULT 'prebuilt-invoice',
            azure_docint_api_version VARCHAR(30) DEFAULT '2024-11-30',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)
        cur.execute("INSERT IGNORE INTO nfe_config (id) VALUES (1)")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS comissao_lancamentos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            cod_vendedor INT DEFAULT 0,
            motorista VARCHAR(180) DEFAULT '',
            entregador VARCHAR(180) DEFAULT '',
            rota VARCHAR(180) DEFAULT '',
            usina VARCHAR(180) DEFAULT '',
            data_faturamento DATE NULL,
            data_saida DATE NULL,
            data_chegada DATE NULL,
            v_gf DECIMAL(12,2) DEFAULT 0,
            d_gf DECIMAL(12,2) DEFAULT 0,
            icms_gf DECIMAL(12,2) DEFAULT 0,
            v_pet DECIMAL(12,2) DEFAULT 0,
            d_pet DECIMAL(12,2) DEFAULT 0,
            icms_pet DECIMAL(12,2) DEFAULT 0,
            v_agua DECIMAL(12,2) DEFAULT 0,
            d_agua DECIMAL(12,2) DEFAULT 0,
            gf_600 DECIMAL(12,3) DEFAULT 0,
            gf_200 DECIMAL(12,3) DEFAULT 0,
            gf_300 DECIMAL(12,3) DEFAULT 0,
            dev_gf DECIMAL(12,3) DEFAULT 0,
            pet_2l DECIMAL(12,3) DEFAULT 0,
            pet_600 DECIMAL(12,3) DEFAULT 0,
            dev_pet DECIMAL(12,3) DEFAULT 0,
            agua_vol DECIMAL(12,3) DEFAULT 0,
            total_pedidos DECIMAL(12,3) DEFAULT 0,
            acucar_qtd DECIMAL(12,3) DEFAULT 0,
            t_acucar DECIMAL(12,3) DEFAULT 0,
            pct_vend_gf DECIMAL(10,6) DEFAULT 0.01,
            pct_vend_pet DECIMAL(10,6) DEFAULT 0.01,
            pct_vend_agua DECIMAL(10,6) DEFAULT 0.03,
            pct_ent_gf DECIMAL(10,6) DEFAULT 0.08,
            pct_ent_pet DECIMAL(10,6) DEFAULT 0.06,
            pct_ent_agua DECIMAL(10,6) DEFAULT 0.06,
            taxa_ent_acucar DECIMAL(10,6) DEFAULT 0,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (cod_vendedor),
            INDEX (motorista),
            INDEX (entregador),
            INDEX (rota),
            INDEX (data_faturamento),
            INDEX (criado_em)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS comissao_cadastros (
            id INT AUTO_INCREMENT PRIMARY KEY,
            codigo INT DEFAULT 0,
            nome VARCHAR(220) NOT NULL,
            funcao VARCHAR(60) NOT NULL,
            pct_gf DECIMAL(10,6) DEFAULT 0,
            pct_pet DECIMAL(10,6) DEFAULT 0,
            pct_agua DECIMAL(10,6) DEFAULT 0,
            ativo TINYINT(1) DEFAULT 1,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (codigo),
            INDEX (nome),
            INDEX (funcao),
            INDEX (ativo)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS comissao_cidades (
            id INT AUTO_INCREMENT PRIMARY KEY,
            rota VARCHAR(220) NOT NULL,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (rota)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vendas_relatorios_importados (
            id VARCHAR(32) PRIMARY KEY,
            source_type VARCHAR(40) NOT NULL DEFAULT 'csv_relatorios_dir',
            source_path VARCHAR(500) NOT NULL DEFAULT '',
            source_name VARCHAR(255) NOT NULL DEFAULT '',
            source_size BIGINT NOT NULL DEFAULT 0,
            source_mtime DATETIME NULL,
            source_signature VARCHAR(700) NOT NULL DEFAULT '',
            rows_importadas INT NOT NULL DEFAULT 0,
            status VARCHAR(30) NOT NULL DEFAULT 'pronto',
            ativo TINYINT(1) NOT NULL DEFAULT 0,
            importado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_vendas_relatorios_importados_ativo (ativo),
            INDEX idx_vendas_relatorios_importados_source_name (source_name)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vendas_relatorio_itens (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            import_id VARCHAR(32) NOT NULL,
            data_ref DATE NULL,
            data_texto VARCHAR(20) DEFAULT '',
            vendedor_key VARCHAR(255) DEFAULT '',
            vendedor_key_upper VARCHAR(255) DEFAULT '',
            vendedor_codigo VARCHAR(80) DEFAULT '',
            vendedor_nome VARCHAR(255) DEFAULT '',
            numero_nf VARCHAR(80) DEFAULT '',
            cliente VARCHAR(255) DEFAULT '',
            cliente_norm VARCHAR(255) DEFAULT '',
            cidade VARCHAR(180) DEFAULT '',
            produto VARCHAR(255) DEFAULT '',
            tipo_operacao VARCHAR(180) DEFAULT '',
            condicao VARCHAR(180) DEFAULT '',
            quantidade DECIMAL(18,3) DEFAULT 0,
            litros DECIMAL(18,3) DEFAULT 0,
            caixas DECIMAL(18,3) DEFAULT 0,
            valor_venda DECIMAL(18,2) DEFAULT 0,
            valor_devolvido DECIMAL(18,2) DEFAULT 0,
            valor_liquido DECIMAL(18,2) DEFAULT 0,
            quantidade_devolvida DECIMAL(18,3) DEFAULT 0,
            litro_devolvido DECIMAL(18,3) DEFAULT 0,
            caixa_devolvida DECIMAL(18,3) DEFAULT 0,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_vendas_relatorio_itens_import (import_id),
            INDEX idx_vendas_relatorio_itens_vendedor (import_id, vendedor_key_upper),
            INDEX idx_vendas_relatorio_itens_data (import_id, data_ref),
            INDEX idx_vendas_relatorio_itens_nf (import_id, numero_nf),
            INDEX idx_vendas_relatorio_itens_cliente (import_id, cliente_norm)
        )
        """)

        
        # 2b) Se as tabelas já existiam antigas, garante colunas esperadas
        try:
            cur.execute("ALTER TABLE manutencoes ADD COLUMN tipo VARCHAR(120) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE manutencoes ADD COLUMN valor DECIMAL(10,2) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE trocas_oleo ADD COLUMN tipo VARCHAR(120) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE trocas_pneu ADD COLUMN marca VARCHAR(120) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE trocas_pneu ADD COLUMN valor_total DECIMAL(10,2) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE trocas_pneu ADD COLUMN quantidade INT DEFAULT 1")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE trocas_pneu ADD COLUMN data_troca DATE NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE trocas_pneu ADD COLUMN localizacao_posicao VARCHAR(60) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE trocas_pneu ADD COLUMN localizacao_lado VARCHAR(60) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE trocas_pneu ADD COLUMN localizacao VARCHAR(60) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE trocas_pneu ADD COLUMN observacao_rodizio VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE trocas_pneu ADD COLUMN data_registro DATETIME DEFAULT CURRENT_TIMESTAMP")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE abastecimentos ADD COLUMN posto VARCHAR(160) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE abastecimentos ADD COLUMN combustivel_tipo VARCHAR(20) DEFAULT 'diesel'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE abastecimentos ADD COLUMN chave_acesso_nfe VARCHAR(64) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE abastecimentos ADD COLUMN numero_nota VARCHAR(120) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE abastecimentos ADD COLUMN emitente_nome VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE abastecimentos ADD COLUMN valor DECIMAL(10,2) NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE abastecimentos ADD COLUMN quantidade_litros DECIMAL(10,3) NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE abastecimentos ADD COLUMN status VARCHAR(30) DEFAULT 'liberado'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE abastecimentos ADD COLUMN data_liberacao DATETIME DEFAULT CURRENT_TIMESTAMP")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE abastecimentos ADD COLUMN data_abastecimento DATETIME NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE fretes ADD COLUMN entregador_id INT NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE fretes ADD COLUMN cidade VARCHAR(180) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE fretes ADD COLUMN data_carga DATE NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE fretes ADD COLUMN km_atual INT DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE fretes ADD COLUMN peso DECIMAL(10,3) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE fretes ADD COLUMN qtd_entregas INT DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE fretes ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE fretes ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE fretes ADD COLUMN finalizado_em DATETIME NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE fretes ADD INDEX idx_fretes_status (status)")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE fretes ADD INDEX idx_fretes_finalizado_em (finalizado_em)")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE lavagens ADD COLUMN data_lavagem DATE NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE lavagens ADD COLUMN km INT DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE lavagens ADD COLUMN local VARCHAR(160) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE lavagens ADD COLUMN valor DECIMAL(10,2) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE lavagens ADD COLUMN observacao VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE lavagens ADD COLUMN data_registro DATETIME DEFAULT CURRENT_TIMESTAMP")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN codigo_barras VARCHAR(120) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN numero_nota VARCHAR(120) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN nome_produto VARCHAR(255) NOT NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN quantidade DECIMAL(12,3) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN valor_unitario DECIMAL(12,2) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN tipo_movimento VARCHAR(20) DEFAULT 'entrada'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN origem_setor VARCHAR(80) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN destino_setor VARCHAR(80) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN referencia_tipo VARCHAR(60) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN referencia_id INT NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN usuario_registro VARCHAR(180) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_movimentos ADD COLUMN data_registro DATETIME DEFAULT CURRENT_TIMESTAMP")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_produtos ADD COLUMN codigo_barras VARCHAR(120) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_produtos ADD COLUMN codigo_produto_nfe VARCHAR(120) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_produtos ADD COLUMN nome_produto VARCHAR(255) NOT NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_produtos ADD COLUMN unidade VARCHAR(30) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_produtos ADD COLUMN embalagem_tipo_padrao VARCHAR(30) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_produtos ADD COLUMN fator_embalagem_padrao DECIMAL(12,3) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_produtos ADD COLUMN origem_cadastro VARCHAR(40) DEFAULT 'manual'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_produtos ADD COLUMN criado_em DATETIME DEFAULT CURRENT_TIMESTAMP")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_produtos ADD COLUMN atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN numero_nota VARCHAR(120) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN chave_acesso VARCHAR(64) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN serie VARCHAR(30) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN emitente_nome VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN emitente_cnpj VARCHAR(32) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN destinatario_nome VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN destinatario_cnpj VARCHAR(32) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN data_emissao VARCHAR(40) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN status VARCHAR(30) DEFAULT 'pendente'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN origem_setor VARCHAR(80) DEFAULT 'Fabrica'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN destino_setor VARCHAR(80) DEFAULT 'Almoxarifado'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN arquivo_origem VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN recebido_por VARCHAR(180) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN criado_em DATETIME DEFAULT CURRENT_TIMESTAMP")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencias ADD COLUMN confirmado_em DATETIME NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN conferencia_id INT NOT NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN item_seq VARCHAR(30) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN produto_id INT NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN codigo_produto_nfe VARCHAR(120) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN codigo_barras VARCHAR(120) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN nome_produto VARCHAR(255) NOT NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN unidade VARCHAR(30) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN embalagem_tipo VARCHAR(30) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN quantidade_embalagem DECIMAL(12,3) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN fator_embalagem DECIMAL(12,3) DEFAULT 1")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN fator_inferido TINYINT(1) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN quantidade_nfe DECIMAL(12,3) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN quantidade_conferida DECIMAL(12,3) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN valor_unitario DECIMAL(12,2) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN estoque_movimento_id INT NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN consolidado_em DATETIME NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE estoque_conferencia_itens ADD COLUMN criado_em DATETIME DEFAULT CURRENT_TIMESTAMP")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE usuarios ADD COLUMN ativo TINYINT(1) DEFAULT 1")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE usuarios ADD COLUMN sip_habilitado TINYINT(1) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE usuarios ADD COLUMN sip_usuario VARCHAR(160) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE usuarios ADD COLUMN sip_senha VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE usuarios ADD COLUMN sip_ramal VARCHAR(160) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE usuarios ADD COLUMN codbar_modo VARCHAR(20) DEFAULT 'bip'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE sip_config ADD COLUMN caller_id_template VARCHAR(255) DEFAULT '{nome} RioBranco'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE sip_config ADD COLUMN modo_ativo VARCHAR(30) DEFAULT 'freepbx'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE sip_config ADD COLUMN setevoip_config_json LONGTEXT NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE sip_config ADD COLUMN freepbx_config_json LONGTEXT NULL")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE chat_mensagens ADD COLUMN lida TINYINT(1) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE chat_mensagens ADD COLUMN anexo_nome VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE chat_mensagens ADD COLUMN anexo_path VARCHAR(500) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE chat_mensagens ADD COLUMN anexo_mime VARCHAR(160) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE chat_mensagens ADD COLUMN anexo_tamanho BIGINT DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE logs_exclusoes ADD COLUMN descricao VARCHAR(500) NOT NULL DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE comissao_lancamentos ADD COLUMN usina VARCHAR(180) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE nfe_config ADD COLUMN ambiente VARCHAR(20) DEFAULT 'producao'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE nfe_config ADD COLUMN uf_autor VARCHAR(2) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE nfe_config ADD COLUMN ultimo_nsu VARCHAR(20) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE nfe_config ADD COLUMN auto_manifestar_ciencia TINYINT(1) DEFAULT 1")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE nfe_config ADD COLUMN azure_docint_habilitado TINYINT(1) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE nfe_config ADD COLUMN azure_docint_endpoint VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE nfe_config ADD COLUMN azure_docint_key VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE nfe_config ADD COLUMN azure_docint_model_id VARCHAR(120) DEFAULT 'prebuilt-invoice'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE nfe_config ADD COLUMN azure_docint_api_version VARCHAR(30) DEFAULT '2024-11-30'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE vendas_relatorios_importados ADD COLUMN ativo TINYINT(1) DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE vendas_relatorios_importados ADD COLUMN source_name VARCHAR(255) NOT NULL DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE vendas_relatorios_importados ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE vendas_relatorio_itens ADD COLUMN vendedor_key_upper VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE vendas_relatorio_itens ADD COLUMN cliente_norm VARCHAR(255) DEFAULT ''")
        except Exception:
            pass
        _sincronizar_usuarios_sip(conn)
        conn.commit()
        cur.close()
    except Exception as e:
        print("WARN ensure_schema:", e)
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

# Executa migração ao subir o servidor


# =========================================================
# (2) HELPERS
# =========================================================
def _as_int(v, default=0):
    try:
        if v is None or str(v).strip() == "":
            return default
        return int(float(str(v)))
    except:
        return default

def _as_float(v, default=0.0):
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).replace(",", "."))
    except:
        return default

def _as_float_br(v, default=0.0):
    s = _as_str(v).replace(" ", "")
    if not s:
        return default
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return default

def _as_str(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()

def _as_date(v):
    s = _as_str(v)
    if not s:
        return None
    try:
        return datetime.datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None

def _nz(v):
    return _as_float(v, 0.0)

def _calc_comissao_lancamento(row):
    base_gf = _nz(row.get("v_gf")) - _nz(row.get("d_gf")) - _nz(row.get("icms_gf"))
    base_pet = _nz(row.get("v_pet")) - _nz(row.get("d_pet")) - _nz(row.get("icms_pet"))
    base_agua = _nz(row.get("v_agua")) - _nz(row.get("d_agua"))
    base_vendedor_total = base_gf + base_pet + base_agua

    com_vendedor = (
        (base_gf * _nz(row.get("pct_vend_gf"))) +
        (base_pet * _nz(row.get("pct_vend_pet"))) +
        (base_agua * _nz(row.get("pct_vend_agua")))
    )

    base_ent_gf = _nz(row.get("gf_600")) + _nz(row.get("gf_200")) + _nz(row.get("gf_300")) - _nz(row.get("dev_gf"))
    base_ent_pet = _nz(row.get("pet_2l")) + _nz(row.get("pet_600")) - _nz(row.get("dev_pet"))
    base_ent_agua = _nz(row.get("agua_vol"))
    base_ent_acucar = _nz(row.get("acucar_qtd"))
    taxa_acucar = _nz(row.get("taxa_ent_acucar"))
    if taxa_acucar <= 0:
        taxa_acucar = _nz(row.get("t_acucar"))

    com_entregador = (
        (base_ent_gf * _nz(row.get("pct_ent_gf"))) +
        (base_ent_pet * _nz(row.get("pct_ent_pet"))) +
        (base_ent_agua * _nz(row.get("pct_ent_agua"))) +
        (base_ent_acucar * taxa_acucar)
    )

    return {
        "base_gf": base_gf,
        "base_pet": base_pet,
        "base_agua": base_agua,
        "base_vendedor_total": base_vendedor_total,
        "comissao_vendedor": com_vendedor,
        "base_ent_gf": base_ent_gf,
        "base_ent_pet": base_ent_pet,
        "base_ent_agua": base_ent_agua,
        "base_ent_acucar": base_ent_acucar,
        "comissao_entregador": com_entregador,
    }

def _fmt_dt(v):
    if not v:
        return None
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)

def _fmt_date(v):
    if not v:
        return None
    if isinstance(v, datetime.datetime):
        return v.date().strftime("%Y-%m-%d")
    if isinstance(v, datetime.date):
        return v.strftime("%Y-%m-%d")
    return _as_str(v)[:10] or None

def _json_list_or_empty(s):
    try:
        return json.loads(s) if s else []
    except:
        return []

def _json_obj_or_empty(s):
    try:
        obj = json.loads(s) if s else {}
        return obj if isinstance(obj, dict) else {}
    except:
        return {}

def _load_json_file(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if default is None:
            return data
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default

def _save_json_file(path, data):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)

def _normalizar_codbar_modo(v):
    modo = _as_str(v).lower()
    return "camera" if modo == "camera" else "bip"

def _normalizar_codigo_barras(v):
    codigo = _as_str(v)
    if codigo.upper() in ("SEM GTIN", "SEMGTIN", "NO GTIN"):
        return ""
    return codigo

def _normalizar_chave_acesso_nfe(v):
    return re.sub(r"\D+", "", _as_str(v))

def _normalizar_combustivel_tipo(v):
    tipo = _as_str(v).strip().lower()
    if tipo in ("arla", "arla32", "arla 32"):
        return "arla"
    return "diesel"

def _combustivel_tipo_label(v):
    return "Arla" if _normalizar_combustivel_tipo(v) == "arla" else "Diesel"

def _detectar_combustivel_tipo_item(nome_produto):
    nome = _as_str(nome_produto).upper()
    if not nome:
        return ""
    if "ARLA" in nome:
        return "arla"
    if any(token in nome for token in ("DIESEL", "S10", "S-10", "S500", "S-500")):
        return "diesel"
    return ""

def _xml_local_name(tag):
    return str(tag or "").split("}", 1)[-1]

def _xml_child(node, tag_name):
    if node is None:
        return None
    for child in list(node):
        if _xml_local_name(child.tag) == tag_name:
            return child
    return None

def _xml_children(node, tag_name):
    if node is None:
        return []
    return [child for child in list(node) if _xml_local_name(child.tag) == tag_name]

def _xml_text(node, *path):
    current = node
    for tag_name in path:
        current = _xml_child(current, tag_name)
        if current is None:
            return ""
    return _as_str(current.text)

def _parse_nfe_xml_text(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        raise ValueError(f"XML da NF-e invalido: {exc}") from exc

    root_name = _xml_local_name(root.tag)
    nfe_node = root if root_name == "NFe" else _xml_child(root, "NFe")
    if nfe_node is None:
        raise ValueError("Nao foi encontrado o bloco NFe no XML informado.")

    inf_nfe = _xml_child(nfe_node, "infNFe")
    if inf_nfe is None:
        raise ValueError("Nao foi encontrado o bloco infNFe no XML informado.")

    ide = _xml_child(inf_nfe, "ide")
    emit = _xml_child(inf_nfe, "emit")
    dest = _xml_child(inf_nfe, "dest")
    prot = _xml_child(root, "protNFe")
    inf_prot = _xml_child(prot, "infProt") if prot is not None else None

    chave_acesso = _xml_text(inf_prot, "chNFe")
    if not chave_acesso:
        raw_id = _as_str((inf_nfe.attrib or {}).get("Id"))
        chave_acesso = raw_id[3:] if raw_id.startswith("NFe") else raw_id

    itens = []
    for idx, det in enumerate(_xml_children(inf_nfe, "det"), start=1):
        prod = _xml_child(det, "prod")
        if prod is None:
            continue
        codigo_barras = _normalizar_codigo_barras(_xml_text(prod, "cEAN") or _xml_text(prod, "cEANTrib"))
        codigo_produto = _as_str(_xml_text(prod, "cProd"))
        nome_produto = _as_str(_xml_text(prod, "xProd"))
        unidade = _as_str(_xml_text(prod, "uCom") or _xml_text(prod, "uTrib"))
        quantidade = _as_float(_xml_text(prod, "qCom") or _xml_text(prod, "qTrib"), 0.0)
        valor_unitario = _as_float(_xml_text(prod, "vUnCom") or _xml_text(prod, "vUnTrib"), 0.0)
        valor_total = _as_float(_xml_text(prod, "vProd"), quantidade * valor_unitario)
        itens.append({
            "item_seq": _as_str((det.attrib or {}).get("nItem")) or str(idx),
            "codigo_produto_nfe": codigo_produto,
            "codigo_barras": codigo_barras,
            "nome_produto": nome_produto,
            "unidade": unidade,
            "quantidade": quantidade,
            "valor_unitario": valor_unitario,
            "valor_total": valor_total,
        })

    if not itens:
        raise ValueError("A NF-e nao possui itens validos para importar.")

    return _aplicar_cadastro_embalagem_preview({
        "numero_nota": _xml_text(ide, "nNF"),
        "serie": _xml_text(ide, "serie"),
        "chave_acesso": chave_acesso,
        "data_emissao": _xml_text(ide, "dhEmi") or _xml_text(ide, "dEmi"),
        "emitente_nome": _xml_text(emit, "xNome"),
        "emitente_cnpj": _xml_text(emit, "CNPJ") or _xml_text(emit, "CPF"),
        "destinatario_nome": _xml_text(dest, "xNome"),
        "destinatario_cnpj": _xml_text(dest, "CNPJ") or _xml_text(dest, "CPF"),
        "itens": itens,
    })

def _ler_xml_nfe_requisicao():
    arquivo_origem = ""
    xml_text = ""
    file_storage = request.files.get("xml")
    if file_storage:
        arquivo_origem = secure_filename(file_storage.filename or "")
        xml_bytes = file_storage.read() or b""
        if not xml_bytes:
            raise ValueError("arquivo XML vazio")
        try:
            xml_text = xml_bytes.decode("utf-8-sig")
        except Exception:
            xml_text = xml_bytes.decode("latin-1", errors="ignore")
    else:
        data = request.get_json(silent=True) or {}
        xml_text = _as_str(data.get("xml_text") or data.get("xml"))
        arquivo_origem = _as_str(data.get("arquivo_origem"))
    return xml_text, arquivo_origem

def _ler_arquivo_nfe_requisicao():
    arquivo_origem = ""
    conteudo = b""
    mimetype = ""
    file_storage = request.files.get("arquivo") or request.files.get("xml") or request.files.get("pdf")
    if file_storage:
        arquivo_origem = secure_filename(file_storage.filename or "")
        mimetype = _as_str(file_storage.mimetype).lower()
        conteudo = file_storage.read() or b""
        if not conteudo:
            raise ValueError("arquivo enviado vazio")
        return conteudo, arquivo_origem, mimetype

    data = request.get_json(silent=True) or {}
    xml_text = _as_str(data.get("xml_text") or data.get("xml"))
    if xml_text:
        arquivo_origem = _as_str(data.get("arquivo_origem")) or "nfe.xml"
        return xml_text.encode("utf-8"), arquivo_origem, "application/xml"
    html_text = _as_str(data.get("html_text") or data.get("html"))
    if html_text:
        arquivo_origem = _as_str(data.get("arquivo_origem")) or "consulta_nfe.html"
        return html_text.encode("utf-8"), arquivo_origem, "text/html"
    return b"", "", ""

def _detectar_tipo_arquivo_nfe(conteudo, arquivo_origem="", mimetype=""):
    nome = _as_str(arquivo_origem).lower()
    tipo = _as_str(mimetype).lower()
    prefixo = (conteudo or b"")[:16].lstrip()
    prefixo_texto = _decode_xml_bytes((conteudo or b"")[:2048]).lower() if conteudo else ""
    if (
        nome.endswith(".html")
        or nome.endswith(".htm")
        or tipo == "text/html"
        or "<html" in prefixo_texto
        or "xsltnferesumida" in prefixo_texto
        or "tabnfe" in prefixo_texto
    ):
        return "html"
    if nome.endswith(".xml") or tipo in ("text/xml", "application/xml") or prefixo.startswith(b"<"):
        return "xml"
    if nome.endswith(".pdf") or tipo == "application/pdf" or prefixo.startswith(b"%PDF"):
        return "pdf"
    return ""

def _decode_xml_bytes(xml_bytes):
    try:
        return (xml_bytes or b"").decode("utf-8-sig")
    except Exception:
        return (xml_bytes or b"").decode("latin-1", errors="ignore")

def _normalizar_data_documento(v):
    s = _as_str(v)
    if not s:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s[:10]):
        return s[:10]
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s[:10], fmt).date().isoformat()
        except Exception:
            pass
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return ""

def _pdf_literal_to_text(data):
    out = bytearray()
    i = 0
    data = data or b""
    while i < len(data):
        b = data[i]
        if b == 92 and i + 1 < len(data):  # backslash
            nxt = data[i + 1]
            mapa = {
                ord("n"): 10,
                ord("r"): 13,
                ord("t"): 9,
                ord("b"): 8,
                ord("f"): 12,
                ord("("): ord("("),
                ord(")"): ord(")"),
                ord("\\"): ord("\\"),
            }
            if nxt in mapa:
                out.append(mapa[nxt])
                i += 2
                continue
            if 48 <= nxt <= 55:
                octal = bytes([nxt])
                j = i + 2
                while j < min(i + 4, len(data)) and 48 <= data[j] <= 55:
                    octal += bytes([data[j]])
                    j += 1
                out.append(int(octal, 8))
                i = j
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(b)
        i += 1
    return out.decode("latin-1", errors="ignore")

def _extrair_texto_stream_pdf(stream_bytes):
    segmentos = []
    for match in re.finditer(rb"\((?:\\.|[^\\()])*\)\s*Tj", stream_bytes or b""):
        bloco = match.group(0)
        fim = bloco.rfind(b")")
        if fim > 0:
            segmentos.append(_pdf_literal_to_text(bloco[1:fim]))
    for match in re.finditer(rb"\[(.*?)\]\s*TJ", stream_bytes or b"", re.S):
        partes = []
        for literal in re.finditer(rb"\((?:\\.|[^\\()])*\)", match.group(1)):
            partes.append(_pdf_literal_to_text(literal.group(0)[1:-1]))
        if partes:
            segmentos.append("".join(partes))
    for match in re.finditer(rb"\((?:\\.|[^\\()])*\)\s*[\"']", stream_bytes or b""):
        bloco = match.group(0)
        fim = bloco.rfind(b")")
        if fim > 0:
            segmentos.append(_pdf_literal_to_text(bloco[1:fim]))
    return "\n".join([_as_str(seg) for seg in segmentos if _as_str(seg)])

def _descompactar_stream_pdf(stream_bytes):
    candidatos = [stream_bytes or b"", (stream_bytes or b"").rstrip(b"\r\n")]
    for candidato in candidatos:
        if not candidato:
            continue
        try:
            return zlib.decompress(candidato)
        except Exception:
            try:
                return zlib.decompress(candidato, -15)
            except Exception:
                pass
    return b""

def _extrair_texto_pdf_bytes(pdf_bytes):
    textos = []
    if shutil.which("pdftotext"):
        tmp_pdf_path = os.path.join("/tmp", f"nfe_pdf_{uuid.uuid4().hex}.pdf")
        tmp_txt_path = os.path.join("/tmp", f"nfe_pdf_{uuid.uuid4().hex}.txt")
        try:
            with open(tmp_pdf_path, "wb") as f:
                f.write(pdf_bytes or b"")
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp_pdf_path, tmp_txt_path],
                capture_output=True,
                text=True,
                errors="ignore",
                timeout=20,
                check=False,
            )
            if proc.returncode == 0 and os.path.exists(tmp_txt_path):
                with open(tmp_txt_path, "r", encoding="utf-8", errors="ignore") as f:
                    texto_extraido = f.read()
                if _as_str(texto_extraido):
                    textos.append(texto_extraido)
        except Exception:
            pass
        finally:
            for path in (tmp_pdf_path, tmp_txt_path):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass

    for match in re.finditer(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream", pdf_bytes or b"", re.S):
        header = match.group(1) or b""
        stream = match.group(2) or b""
        if b"/FlateDecode" in header:
            payload = _descompactar_stream_pdf(stream)
        else:
            payload = stream
        texto = _extrair_texto_stream_pdf(payload)
        if _as_str(texto):
            textos.append(texto)

    if not textos and shutil.which("strings"):
        tmp_path = os.path.join("/tmp", f"nfe_pdf_{uuid.uuid4().hex}.pdf")
        try:
            with open(tmp_path, "wb") as f:
                f.write(pdf_bytes or b"")
            proc = subprocess.run(
                ["strings", "-n", "4", tmp_path],
                capture_output=True,
                text=True,
                errors="ignore",
                timeout=20,
                check=False,
            )
            if _as_str(proc.stdout):
                textos.append(proc.stdout)
        except Exception:
            pass
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    return "\n".join([t for t in textos if _as_str(t)])

def _linhas_pdf_normalizadas(texto):
    vistos = set()
    linhas = []
    for raw in re.split(r"[\r\n]+", texto or ""):
        linha = re.sub(r"\s+", " ", _as_str(raw))
        if not linha:
            continue
        chave = linha.upper()
        if chave in vistos:
            continue
        vistos.add(chave)
        linhas.append(linha)
    return linhas

def _limpar_numero_nota(v):
    digits = re.sub(r"\D+", "", _as_str(v))
    if not digits or len(digits) > 15:
        return ""
    return digits.lstrip("0") or digits

def _primeira_linha_com_rotulo(linhas, rotulos):
    rotulos = [r.upper() for r in (rotulos or []) if _as_str(r)]
    for idx, linha in enumerate(linhas or []):
        up = linha.upper()
        if not any(rotulo in up for rotulo in rotulos):
            continue
        for prox in (linhas or [])[idx + 1: idx + 4]:
            prox_up = prox.upper()
            if any(rotulo in prox_up for rotulo in rotulos):
                continue
            if re.search(r"[A-Z]", prox_up):
                return prox
    return ""

def _extrair_itens_pdf_linhas(linhas):
    itens = []
    vistos = set()
    skip_terms = (
        "CHAVE DE ACESSO",
        "CONTROLE DO FISCO",
        "NOTA FISCAL",
        "DANFE",
        "CALCULO DO IMPOSTO",
        "BASE DE CALCULO",
        "VALOR DO ICMS",
        "VALOR TOTAL",
        "TRANSPORTADOR",
        "PESO BRUTO",
        "PESO LIQUIDO",
        "DADOS ADICIONAIS",
        "RESERVADO AO FISCO",
        "PROTOCOLO",
        "NATUREZA DA OPERACAO",
        "FATURA",
        "DESCONTO",
        "FRETE",
    )
    item_re = re.compile(
        r"^(?P<prefixo>.+?)\s+(?P<unidade>[A-Z]{1,4})\s+(?P<quantidade>\d[\d.,]*)\s+"
        r"(?P<valor_unitario>\d[\d.,]*)\s+(?P<valor_total>\d[\d.,]*)(?:\s+.*)?$"
    )
    for linha in linhas or []:
        up = linha.upper()
        if any(term in up for term in skip_terms):
            continue
        match = item_re.match(linha)
        if not match:
            continue
        prefixo = re.sub(r"\s+", " ", _as_str(match.group("prefixo")))
        partes = prefixo.split()
        item_seq = ""
        codigo_produto = ""
        if partes and re.fullmatch(r"\d{1,4}", partes[0]):
            item_seq = partes.pop(0)
        if partes and re.fullmatch(r"[A-Z0-9./-]{2,20}", partes[0]) and not re.search(r"[a-z]", partes[0]):
            codigo_produto = partes.pop(0)
        nome = " ".join(partes).strip()
        if not nome or not re.search(r"[A-Za-z]", nome):
            continue
        chave = (
            nome.upper(),
            match.group("unidade"),
            match.group("quantidade"),
            match.group("valor_unitario"),
        )
        if chave in vistos:
            continue
        vistos.add(chave)
        itens.append({
            "item_seq": item_seq or str(len(itens) + 1),
            "codigo_produto_nfe": codigo_produto,
            "codigo_barras": "",
            "nome_produto": nome,
            "unidade": match.group("unidade"),
            "quantidade": _as_float_br(match.group("quantidade"), 0.0),
            "valor_unitario": _as_float_br(match.group("valor_unitario"), 0.0),
            "valor_total": _as_float_br(match.group("valor_total"), 0.0),
        })
    return itens

def _extrair_itens_ocr_linhas(linhas):
    itens = []
    vistos = set()
    skip_terms = (
        "CHAVE DE ACESSO",
        "CONTROLE DO FISCO",
        "NOTA FISCAL",
        "DANFE",
        "VALOR TOTAL",
        "TOTAL DA NOTA",
        "CALCULO DO IMPOSTO",
        "DADOS ADICIONAIS",
        "RESERVADO AO FISCO",
        "PROTOCOLO",
        "DESCONTO",
        "FRETE",
        "ICMS",
        "IPI",
        "CNPJ",
        "EMITENTE",
        "DESTINATARIO",
    )
    patterns = [
        re.compile(
            r"^(?:(?P<seq>\d{1,4})\s+)?(?P<codigo>[A-Z0-9./-]{2,30})\s+(?P<nome>.+?)\s+"
            r"(?P<quantidade>\d[\d.,]*)\s+(?P<valor_unitario>\d[\d.,]*)$",
            re.I,
        ),
        re.compile(
            r"^(?:(?P<seq>\d{1,4})\s+)?(?P<codigo>[A-Z0-9./-]{2,30})\s+(?P<nome>.+?)\s+"
            r"(?P<unidade>[A-Z]{1,4})\s+(?P<quantidade>\d[\d.,]*)\s+(?P<valor_unitario>\d[\d.,]*)"
            r"(?:\s+(?P<valor_total>\d[\d.,]*))?$",
            re.I,
        ),
    ]
    for linha in linhas or []:
        linha = re.sub(r"\s+", " ", _as_str(linha)).strip()
        if not linha:
            continue
        up = linha.upper()
        if any(term in up for term in skip_terms):
            continue
        if not re.search(r"\d", linha) or not re.search(r"[A-Z]", up):
            continue

        match = None
        for pattern in patterns:
            match = pattern.match(linha)
            if match:
                break
        if not match:
            continue

        codigo = _as_str(match.group("codigo")).strip()
        nome = _as_str(match.group("nome")).strip(" -")
        if not codigo or not nome or not re.search(r"[A-Za-z]", nome):
            continue

        quantidade = _as_float_br(match.group("quantidade"), 0.0)
        valor_unitario = _as_float_br(match.group("valor_unitario"), 0.0)
        if quantidade <= 0 or valor_unitario < 0:
            continue

        chave = (codigo.upper(), nome.upper(), round(quantidade, 3), round(valor_unitario, 2))
        if chave in vistos:
            continue
        vistos.add(chave)

        itens.append({
            "item_seq": _as_str(match.groupdict().get("seq")) or str(len(itens) + 1),
            "codigo_produto_nfe": codigo,
            "codigo_barras": "",
            "nome_produto": nome,
            "unidade": _as_str(match.groupdict().get("unidade")),
            "quantidade": quantidade,
            "valor_unitario": valor_unitario,
            "valor_total": _as_float_br(match.groupdict().get("valor_total"), quantidade * valor_unitario),
        })
    return itens

def _normalizar_item_preview_nfe(item, idx=1):
    item = item or {}
    quantidade = _as_float_br(item.get("quantidade"), _as_float(item.get("quantidade"), 0.0))
    unidade = _as_str(item.get("unidade"))
    if re.fullmatch(r"\d[\d.,]*", unidade or ""):
        unidade = ""
    quantidade_embalagem = _as_float_br(item.get("quantidade_embalagem"), _as_float(item.get("quantidade_embalagem"), quantidade))
    fator_embalagem = _as_float_br(item.get("fator_embalagem"), _as_float(item.get("fator_embalagem"), 1.0))
    if fator_embalagem <= 0:
        fator_embalagem = 1.0
    fator_inferido = 1 if item.get("fator_inferido") in (True, 1, "1", "true", "True") else 0
    quantidade_unidades = _as_float_br(item.get("quantidade_unidades"), _as_float(item.get("quantidade_unidades"), quantidade))
    valor_unitario = _as_float_br(item.get("valor_unitario"), _as_float(item.get("valor_unitario"), 0.0))
    valor_total = _as_float_br(item.get("valor_total"), quantidade * valor_unitario)
    return {
        "item_seq": _as_str(item.get("item_seq")) or str(idx),
        "codigo_produto_nfe": _as_str(item.get("codigo_produto_nfe")),
        "codigo_barras": _normalizar_codigo_barras(item.get("codigo_barras")),
        "nome_produto": _as_str(item.get("nome_produto")),
        "unidade": unidade,
        "embalagem_tipo": _as_str(item.get("embalagem_tipo")) or unidade,
        "quantidade_embalagem": quantidade_embalagem,
        "fator_embalagem": fator_embalagem,
        "fator_inferido": fator_inferido,
        "quantidade_unidades": quantidade_unidades,
        "quantidade": quantidade,
        "valor_unitario": valor_unitario,
        "valor_total": valor_total,
    }

def _normalizar_preview_nfe(data):
    data = data or {}
    warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
    itens_brutos = data.get("itens") if isinstance(data.get("itens"), list) else []
    itens = []
    for idx, item in enumerate(itens_brutos, start=1):
        norm = _normalizar_item_preview_nfe(item, idx)
        if not (
            _as_str(norm.get("nome_produto"))
            or _as_str(norm.get("codigo_produto_nfe"))
            or _as_str(norm.get("codigo_barras"))
            or norm.get("quantidade")
            or norm.get("valor_unitario")
        ):
            continue
        itens.append(norm)

    chave_acesso = _normalizar_chave_acesso_nfe(data.get("chave_acesso"))
    if chave_acesso and len(chave_acesso) != 44:
        warnings.append("Chave de acesso com tamanho incompleto. Revise antes de importar.")
    preview_tipo = "parcial" if _as_str(data.get("preview_tipo")).lower() == "parcial" else "completo"
    limitation_message = _as_str(data.get("limitation_message"))
    valor_total = _as_float_br(data.get("valor_total"), _as_float(data.get("valor_total"), 0.0))

    return {
        "source_type": _as_str(data.get("source_type")).lower() or "xml",
        "preview_tipo": preview_tipo,
        "limitation_message": limitation_message,
        "arquivo_origem": _as_str(data.get("arquivo_origem")),
        "numero_nota": _limpar_numero_nota(data.get("numero_nota")) or _as_str(data.get("numero_nota")),
        "serie": _as_str(data.get("serie")),
        "chave_acesso": chave_acesso,
        "data_emissao": _normalizar_data_documento(data.get("data_emissao")),
        "emitente_nome": _as_str(data.get("emitente_nome")),
        "emitente_cnpj": _normalizar_chave_acesso_nfe(data.get("emitente_cnpj")),
        "destinatario_nome": _as_str(data.get("destinatario_nome")),
        "destinatario_cnpj": _normalizar_chave_acesso_nfe(data.get("destinatario_cnpj")),
        "valor_total": valor_total,
        "itens": itens,
        "warnings": [w for w in warnings if _as_str(w)],
    }


class _HtmlTableCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._table_stack = []
        self._current_row = None
        self._current_cell = None

    def handle_starttag(self, tag, attrs):
        nome = str(tag or "").lower()
        attrs_map = {str(k or "").lower(): str(v or "") for k, v in (attrs or [])}
        if nome == "table":
            self._table_stack.append({"class": attrs_map.get("class", ""), "rows": []})
            return
        if not self._table_stack:
            return
        if nome == "tr":
            self._current_row = []
            return
        if nome in ("td", "th") and self._current_row is not None:
            self._current_cell = []

    def handle_endtag(self, tag):
        nome = str(tag or "").lower()
        if nome in ("td", "th"):
            if self._current_row is not None and self._current_cell is not None:
                texto = re.sub(r"\s+", " ", "".join(self._current_cell or [])).strip()
                self._current_row.append(texto)
            self._current_cell = None
            return
        if nome == "tr":
            if self._table_stack and isinstance(self._current_row, list):
                row = [col for col in self._current_row if _as_str(col)]
                if row:
                    self._table_stack[-1]["rows"].append(row)
            self._current_row = None
            self._current_cell = None
            return
        if nome == "table" and self._table_stack:
            self.tables.append(self._table_stack.pop())

    def handle_data(self, data):
        if self._current_cell is not None:
            self._current_cell.append(str(data or ""))


def _html_linhas_limpa(texto):
    bruto = _as_str(texto)
    bruto = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", " ", bruto)
    bruto = re.sub(r"(?i)</?(tr|p|div|li|h\d)\b[^>]*>", "\n", bruto)
    bruto = re.sub(r"(?i)<br\s*/?>", "\n", bruto)
    bruto = re.sub(r"(?s)<[^>]+>", " ", bruto)
    linhas = []
    for linha in html_lib.unescape(bruto).splitlines():
        limpa = re.sub(r"\s+", " ", linha).strip()
        if limpa:
            linhas.append(limpa)
    return linhas


def _portal_match_header(header, *termos):
    base = re.sub(r"[^a-z0-9]+", "", _as_str(header).lower())
    return any(re.sub(r"[^a-z0-9]+", "", _as_str(termo).lower()) in base for termo in termos if _as_str(termo))


def _portal_find_col(headers, *grupos):
    for idx, header in enumerate(headers):
        for grupo in grupos:
            termos = grupo if isinstance(grupo, (list, tuple)) else [grupo]
            if _portal_match_header(header, *termos):
                return idx
    return -1


def _portal_get_value_from_rows(rows, *labels):
    labels_norm = [re.sub(r"[^a-z0-9]+", "", _as_str(label).lower()) for label in labels if _as_str(label)]
    for row in rows or []:
        cols = [_as_str(col).strip() for col in row if _as_str(col).strip()]
        if len(cols) < 2:
            continue
        for idx in range(len(cols) - 1):
            left_norm = re.sub(r"[^a-z0-9]+", "", cols[idx].lower())
            if any(label in left_norm for label in labels_norm):
                return cols[idx + 1]
    return ""


def _portal_get_value_from_text(lines, *labels):
    labels_norm = [re.sub(r"[^a-z0-9]+", "", _as_str(label).lower()) for label in labels if _as_str(label)]
    for idx, linha in enumerate(lines or []):
        linha_norm = re.sub(r"[^a-z0-9]+", "", linha.lower())
        for label in labels_norm:
            if label and label in linha_norm:
                match = re.search(r":\s*(.+)$", linha)
                if match and _as_str(match.group(1)):
                    return _as_str(match.group(1))
                if idx + 1 < len(lines):
                    prox = _as_str(lines[idx + 1])
                    if prox:
                        return prox
    return ""


def _parse_nfe_portal_html(html_text, arquivo_origem=""):
    html_text = _as_str(html_text)
    if not html_text:
        raise ValueError("envie o HTML salvo da consulta publica da NF-e")
    if "XSLTNFeResumida" not in html_text and "tabNFe" not in html_text:
        raise ValueError("o HTML enviado nao parece ser a pagina resumida oficial da NF-e")

    parser = _HtmlTableCollector()
    try:
        parser.feed(html_text)
    except Exception:
        pass

    tabelas = parser.tables or []
    todas_rows = []
    tabelas_itens = []
    for tabela in tabelas:
        rows = tabela.get("rows") or []
        todas_rows.extend(rows)
        if "tabnfe" in _as_str(tabela.get("class")).lower():
            tabelas_itens.append(rows)

    linhas = _html_linhas_limpa(html_text)
    texto_plano = "\n".join(linhas)
    chave_match = re.search(r"((?:\d[\s.-]?){44})", texto_plano)
    chave_acesso = _normalizar_chave_acesso_nfe(chave_match.group(1) if chave_match else "")
    chave_meta = _nfe_resumo_chave_acesso(chave_acesso)

    numero_nota = (
        _portal_get_value_from_rows(todas_rows, "numero", "número", "nnf")
        or _portal_get_value_from_text(linhas, "numero", "número", "nnf")
        or chave_meta.get("numero_nota")
    )
    serie = (
        _portal_get_value_from_rows(todas_rows, "serie", "série")
        or _portal_get_value_from_text(linhas, "serie", "série")
        or chave_meta.get("serie")
    )
    data_emissao = (
        _portal_get_value_from_rows(todas_rows, "data de emissao", "data emissao", "emissao", "emissão")
        or _portal_get_value_from_text(linhas, "data de emissao", "data emissao", "emissao", "emissão")
    )
    emitente_nome = (
        _portal_get_value_from_rows(todas_rows, "nome / razao social", "nome/razao social", "razao social", "emitente")
        or _portal_get_value_from_text(linhas, "nome / razao social", "nome/razao social", "razao social", "emitente")
    )
    emitente_cnpj = (
        _portal_get_value_from_rows(todas_rows, "cnpj", "cpf")
        or _portal_get_value_from_text(linhas, "cnpj", "cpf")
        or chave_meta.get("emitente_cnpj")
    )
    valor_total = (
        _portal_get_value_from_rows(todas_rows, "valor total da nota fiscal", "valor total", "valor da nota", "vnf")
        or _portal_get_value_from_text(linhas, "valor total da nota fiscal", "valor total", "valor da nota", "vnf")
    )

    itens = []
    for rows in tabelas_itens:
        if len(rows) < 2:
            continue
        headers = [re.sub(r"\s+", " ", _as_str(col)).strip() for col in rows[0]]
        idx_codigo = _portal_find_col(headers, ["codigo", "código", "codprod"], ["cod"])
        idx_descricao = _portal_find_col(headers, ["descricao", "descrição", "produto", "xprod"])
        idx_unidade = _portal_find_col(headers, ["unidade", "un", "und", "ucom"])
        idx_quantidade = _portal_find_col(headers, ["quantidade", "qtd", "qtde", "qcom"])
        idx_vunit = _portal_find_col(headers, ["valor unitario", "valor unitário", "vl unit", "vuncom"])
        idx_vtotal = _portal_find_col(headers, ["valor total", "vprod", "valor produto"])
        for row in rows[1:]:
            cols = [_as_str(col).strip() for col in row]
            if not any(cols):
                continue
            descricao = cols[idx_descricao] if 0 <= idx_descricao < len(cols) else ""
            codigo = cols[idx_codigo] if 0 <= idx_codigo < len(cols) else ""
            if not re.search(r"[A-Za-zÀ-ÿ]", descricao or ""):
                ignorar = {idx for idx in (idx_codigo, idx_unidade, idx_quantidade, idx_vunit, idx_vtotal) if idx >= 0}
                for idx_col, valor_col in enumerate(cols):
                    if idx_col in ignorar:
                        continue
                    valor_limpo = _as_str(valor_col).strip()
                    if re.search(r"[A-Za-zÀ-ÿ]", valor_limpo):
                        descricao = valor_limpo
                        break
            if not descricao and not codigo:
                continue
            if _portal_match_header(descricao, "total", "base de calculo", "valor aproximado dos tributos"):
                continue
            quantidade_raw = cols[idx_quantidade] if 0 <= idx_quantidade < len(cols) else ""
            valor_unitario_raw = cols[idx_vunit] if 0 <= idx_vunit < len(cols) else ""
            valor_total_raw = cols[idx_vtotal] if 0 <= idx_vtotal < len(cols) else ""
            quantidade = _as_float_br(quantidade_raw, _as_float(quantidade_raw, 0.0))
            valor_unitario = _as_float_br(valor_unitario_raw, _as_float(valor_unitario_raw, 0.0))
            valor_total_item = _as_float_br(valor_total_raw, quantidade * valor_unitario)
            itens.append({
                "item_seq": str(len(itens) + 1),
                "codigo_produto_nfe": codigo,
                "codigo_barras": "",
                "nome_produto": descricao,
                "unidade": cols[idx_unidade] if 0 <= idx_unidade < len(cols) else "",
                "quantidade": quantidade,
                "valor_unitario": valor_unitario,
                "valor_total": valor_total_item,
            })

    warnings = [
        "Dados extraidos do HTML resumido da consulta publica da NF-e. Revise antes de confirmar a importacao.",
    ]
    if not itens:
        warnings.append("Nenhum item foi localizado automaticamente na tabela tabNFe do HTML. Ajuste manualmente se necessario.")

    return _aplicar_cadastro_embalagem_preview({
        "source_type": "portal",
        "preview_tipo": "completo" if itens else "parcial",
        "limitation_message": "" if itens else "Consulta publica encontrada, mas a tabela de itens nao foi reconhecida por completo.",
        "arquivo_origem": arquivo_origem or "consulta_nfe.html",
        "numero_nota": numero_nota,
        "serie": serie,
        "chave_acesso": chave_acesso or chave_meta.get("chave_acesso"),
        "data_emissao": data_emissao,
        "emitente_nome": emitente_nome,
        "emitente_cnpj": emitente_cnpj,
        "valor_total": valor_total,
        "itens": itens,
        "warnings": warnings,
    })

def _parse_nfe_pdf_bytes(pdf_bytes, arquivo_origem=""):
    texto = _extrair_texto_pdf_bytes(pdf_bytes)
    if not _as_str(texto):
        raise ValueError("Nao foi possivel ler o PDF da NF-e. Envie o XML oficial ou revise manualmente os dados.")

    linhas = _linhas_pdf_normalizadas(texto)
    digits = re.findall(r"(?:\d[\s.-]?){44}", texto)
    chave_acesso = ""
    for candidato in digits:
        normalizado = _normalizar_chave_acesso_nfe(candidato)
        if len(normalizado) == 44:
            chave_acesso = normalizado
            break

    numero_nota = ""
    serie = ""
    data_emissao = ""
    for linha in linhas:
        up = linha.upper()
        if not numero_nota and ("NOTA" in up or "NUMERO" in up or "NRO" in up):
            for match in re.finditer(r"(\d[\d./-]{2,18})", linha):
                candidato = _limpar_numero_nota(match.group(1))
                if candidato:
                    numero_nota = candidato
                    break
        if not serie and "SERIE" in up:
            match = re.search(r"SERIE\s*[:\-]?\s*([A-Z0-9.-]+)", linha, re.I)
            if match:
                serie = _as_str(match.group(1))
        if not data_emissao and ("EMISSAO" in up or "EMISSAO" in up):
            match = re.search(r"(\d{2}/\d{2}/\d{4})", linha)
            if match:
                data_emissao = _normalizar_data_documento(match.group(1))

    if not data_emissao:
        match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", texto)
        if match:
            data_emissao = _normalizar_data_documento(match.group(1))

    cnpjs = re.findall(r"\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}", texto)
    emitente_nome = _primeira_linha_com_rotulo(linhas, ["EMITENTE", "EMISSOR", "RAZAO SOCIAL"])
    if not emitente_nome:
        for linha in linhas[:12]:
            up = linha.upper()
            if re.search(r"[A-Z]", up) and not any(
                termo in up for termo in ("DANFE", "NOTA FISCAL", "CHAVE DE ACESSO", "CONTROLE DO FISCO")
            ):
                emitente_nome = linha
                break
    destinatario_nome = _primeira_linha_com_rotulo(linhas, ["DESTINATARIO", "REMETENTE"])

    warnings = [
        "Leitura de PDF em modo assistido. Revise os campos e os itens antes de confirmar a importacao."
    ]
    itens = _extrair_itens_pdf_linhas(linhas)
    if not itens:
        warnings.append("Nenhum item foi identificado automaticamente no PDF. Adicione ou ajuste os itens manualmente.")

    return _normalizar_preview_nfe({
        "source_type": "pdf",
        "arquivo_origem": arquivo_origem,
        "numero_nota": numero_nota,
        "serie": serie,
        "chave_acesso": chave_acesso,
        "data_emissao": data_emissao,
        "emitente_nome": emitente_nome,
        "emitente_cnpj": cnpjs[0] if len(cnpjs) >= 1 else "",
        "destinatario_nome": destinatario_nome,
        "destinatario_cnpj": cnpjs[1] if len(cnpjs) >= 2 else "",
        "itens": itens,
        "warnings": warnings,
    })

def _ler_arquivo_imagem_requisicao():
    arquivo = request.files.get("arquivo")
    if not arquivo or not getattr(arquivo, "filename", ""):
        raise ValueError("envie uma foto da nota para leitura OCR")
    conteudo = arquivo.read()
    if not conteudo:
        raise ValueError("a foto enviada esta vazia")
    return conteudo, secure_filename(arquivo.filename or "nota.jpg"), _as_str(getattr(arquivo, "mimetype", "")) or "image/jpeg"

def _normalizar_valor_brasileiro(valor_texto):
    bruto = _as_str(valor_texto)
    if not bruto:
        return None, ""
    match = re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+\.\d{2}|\d+,\d{2})", bruto)
    if not match:
        return None, ""
    token = match.group(1).strip()
    normalizado = token.replace(".", "").replace(",", ".")
    try:
        valor = round(float(normalizado), 2)
    except (TypeError, ValueError):
        return None, ""
    return valor, token

def _extrair_campo_rotulado_ocr(linhas, rotulos):
    rotulos_upper = [r.upper() for r in (rotulos or []) if _as_str(r)]
    for linha in linhas:
        up = linha.upper()
        if not any(rotulo in up for rotulo in rotulos_upper):
            continue
        partes = re.split(r"[:\-]", linha, maxsplit=1)
        if len(partes) == 2 and _as_str(partes[1]):
            return _as_str(partes[1])
        tokens = [tok for tok in re.split(r"\s{2,}", linha) if _as_str(tok)]
        if len(tokens) >= 2:
            return _as_str(tokens[-1])
    return ""

def _extrair_dados_ocr_nfe(texto, arquivo_origem=""):
    texto = _as_str(texto)
    linhas = [_as_str(l).strip() for l in texto.splitlines() if _as_str(l).strip()]
    texto_upper = texto.upper()
    digits_all = re.sub(r"\D", "", texto)

    chave_acesso = ""
    match = re.search(r"CHAVE\s+DE\s+ACESSO(.{0,120})", texto_upper, re.S)
    if match:
        candidato = re.sub(r"\D", "", match.group(1))
        if len(candidato) >= 44:
            chave_acesso = candidato[:44]
    if len(chave_acesso) != 44:
        sequencias = re.findall(r"\d{44}", digits_all)
        if sequencias:
            chave_acesso = sequencias[0]

    numero_nota = ""
    serie = ""
    data_emissao = ""
    emitente_nome = ""
    destinatario_nome = ""
    emitente_cnpj = ""
    destinatario_cnpj = ""
    valor_total = None
    valor_total_label = ""

    for linha in linhas[:40]:
        up = linha.upper()
        if not numero_nota and any(rotulo in up for rotulo in ("NUMERO", "NRO", "N. NF", "NR. NF", "NF-E N")):
            match = re.search(r"(\d{1,9})", linha)
            if match:
                numero_nota = _as_str(match.group(1))
        if not serie and "SERIE" in up:
            match = re.search(r"SERIE\s*[:\-]?\s*([A-Z0-9.-]+)", linha, re.I)
            if match:
                serie = _as_str(match.group(1))
        if not data_emissao and any(rotulo in up for rotulo in ("EMISSAO", "DATA", "DT.")):
            match = re.search(r"(\d{2}/\d{2}/\d{4})", linha)
            if match:
                data_emissao = _normalizar_data_documento(match.group(1))
        if valor_total is None and any(rotulo in up for rotulo in ("VALOR TOTAL", "TOTAL DA NOTA", "VALOR A PAGAR")):
            valor_total, valor_total_label = _normalizar_valor_brasileiro(linha)

    if not data_emissao:
        match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", texto)
        if match:
            data_emissao = _normalizar_data_documento(match.group(1))

    cnpjs = re.findall(r"\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}", texto)
    if cnpjs:
        emitente_cnpj = cnpjs[0]
    if len(cnpjs) >= 2:
        destinatario_cnpj = cnpjs[1]

    emitente_nome = _primeira_linha_com_rotulo(linhas, ["EMITENTE", "EMISSOR", "RAZAO SOCIAL"])
    destinatario_nome = _primeira_linha_com_rotulo(linhas, ["DESTINATARIO", "DESTINATARIO/REMETENTE", "REMETENTE"])

    if not emitente_nome:
        for linha in linhas[:12]:
            up = linha.upper()
            if re.search(r"[A-Z]", up) and not any(
                termo in up
                for termo in (
                    "DANFE",
                    "NOTA FISCAL",
                    "CHAVE DE ACESSO",
                    "CONTROLE DO FISCO",
                    "DOCUMENTO AUXILIAR",
                )
            ):
                emitente_nome = linha
                break

    if valor_total is None:
        for linha in reversed(linhas[-20:]):
            valor_total, valor_total_label = _normalizar_valor_brasileiro(linha)
            if valor_total is not None:
                break

    if not numero_nota:
        campo_numero = _extrair_campo_rotulado_ocr(linhas, ["NUMERO", "NRO", "NF-E"])
        match = re.search(r"(\d{1,9})", campo_numero)
        if match:
            numero_nota = _as_str(match.group(1))

    warnings = [
        "Leitura por OCR em modo assistido. Revise os campos antes de usar a chave ou concluir o lancamento."
    ]
    if len(chave_acesso) != 44:
        warnings.append("A chave de acesso nao foi localizada por completo na foto.")

    return {
        "source_type": "ocr",
        "arquivo_origem": arquivo_origem,
        "texto_bruto": texto,
        "chave_acesso": chave_acesso if len(chave_acesso) == 44 else "",
        "numero_nota": numero_nota,
        "serie": serie,
        "data_emissao": data_emissao,
        "emitente_nome": emitente_nome,
        "emitente_cnpj": emitente_cnpj,
        "destinatario_nome": destinatario_nome,
        "destinatario_cnpj": destinatario_cnpj,
        "valor_total": valor_total,
        "valor_total_label": valor_total_label,
        "warnings": warnings,
    }

def _preparar_candidatos_ocr_imagem(image):
    from PIL import Image, ImageOps

    base = ImageOps.exif_transpose(image).convert("RGB")
    max_lado = 1800
    if max(base.size) > max_lado:
        fator = max_lado / float(max(base.size) or 1)
        novo_tamanho = (
            max(1, int(base.width * fator)),
            max(1, int(base.height * fator)),
        )
        base = base.resize(novo_tamanho, Image.Resampling.LANCZOS)

    candidates = [base]
    cinza = ImageOps.grayscale(base)
    candidates.append(cinza)
    candidates.append(ImageOps.autocontrast(cinza))
    return candidates

def _coletar_textos_ocr_imagem(candidates, pytesseract):
    tentativas = []
    if candidates:
        tentativas.append((candidates[0], "por+eng", "--psm 6"))
    if len(candidates) >= 2:
        tentativas.append((candidates[1], "por+eng", "--psm 6"))
    if len(candidates) >= 3:
        tentativas.append((candidates[2], "por+eng", "--psm 11"))
    tentativas.append((candidates[-1], "eng", "--psm 6"))

    textos = []
    for img, lang, config in tentativas:
        try:
            texto = _as_str(pytesseract.image_to_string(img, lang=lang, config=config, timeout=20))
        except Exception:
            texto = ""
        if texto and texto not in textos:
            textos.append(texto)
    return textos

def _coletar_textos_ocr_itens_imagem(candidates, pytesseract):
    base = candidates[-1] if len(candidates) >= 3 else (candidates[1] if len(candidates) >= 2 else candidates[0])
    tentativas = [
        (base, "eng", "--oem 1 --psm 6 -c preserve_interword_spaces=1"),
        (base, "por+eng", "--oem 1 --psm 6 -c preserve_interword_spaces=1"),
    ]
    textos = []
    for img, lang, config in tentativas:
        try:
            texto = _as_str(pytesseract.image_to_string(img, lang=lang, config=config, timeout=8))
        except Exception:
            texto = ""
        if texto and texto not in textos:
            textos.append(texto)
        if texto and len(texto) > 80:
            break
    return textos

def _carregar_dependencias_ocr():
    try:
        from io import BytesIO
        from PIL import Image
        import pytesseract
    except Exception as exc:
        raise RuntimeError(
            "OCR de notas indisponivel nesta instalacao. Recrie o app com Pillow, pytesseract e tesseract-ocr."
        ) from exc
    return BytesIO, Image, pytesseract

def _get_rapidocr_engine():
    global _rapidocr_engine
    if _rapidocr_engine is not None:
        return _rapidocr_engine
    with _rapidocr_lock:
        if _rapidocr_engine is not None:
            return _rapidocr_engine
        try:
            from rapidocr import RapidOCR
        except Exception as exc:
            raise RuntimeError("RapidOCR indisponivel nesta instalacao.") from exc
        _rapidocr_engine = RapidOCR()
        return _rapidocr_engine

def _ocr_nfe_imagem_bytes(image_bytes, arquivo_origem=""):
    BytesIO, Image, pytesseract = _carregar_dependencias_ocr()

    try:
        image = Image.open(BytesIO(image_bytes))
        image.load()
    except Exception as exc:
        raise ValueError("nao foi possivel abrir a imagem enviada") from exc

    try:
        candidates = _preparar_candidatos_ocr_imagem(image)
    except Exception:
        candidates = [image]

    textos = _coletar_textos_ocr_imagem(candidates, pytesseract)
    melhor = None
    melhor_score = -1

    for texto in textos:
        extraido = _extrair_dados_ocr_nfe(texto, arquivo_origem=arquivo_origem)
        score = 0
        if extraido.get("chave_acesso"):
            score += 10
        if extraido.get("numero_nota"):
            score += 2
        if extraido.get("emitente_nome"):
            score += 2
        if extraido.get("valor_total") is not None:
            score += 1
        if score > melhor_score:
            melhor = extraido
            melhor_score = score
        if extraido.get("chave_acesso"):
            return extraido

    if not melhor and textos:
        melhor = _extrair_dados_ocr_nfe("\n".join(textos), arquivo_origem=arquivo_origem)
    if not melhor:
        raise ValueError("nenhum texto foi identificado na foto da nota")
    return melhor

def _ocr_itens_nfe_imagem_bytes(image_bytes, arquivo_origem=""):
    BytesIO, Image, pytesseract = _carregar_dependencias_ocr()

    try:
        image = Image.open(BytesIO(image_bytes))
        image.load()
    except Exception as exc:
        raise ValueError("nao foi possivel abrir a imagem enviada") from exc

    try:
        candidates = _preparar_candidatos_ocr_imagem(image)
    except Exception:
        candidates = [image]

    melhor_itens = []

    try:
        import numpy as np
        rapid_engine = _get_rapidocr_engine()
        base_img = candidates[-1] if len(candidates) >= 3 else candidates[0]
        rapid_result = rapid_engine(np.array(base_img), use_cls=False)
        rapid_txts = []
        if rapid_result is not None:
            txts = getattr(rapid_result, "txts", None)
            if txts:
                rapid_txts = [_as_str(txt).strip() for txt in txts if _as_str(txt).strip()]
        if rapid_txts:
            itens_rapid = _extrair_itens_ocr_linhas(rapid_txts)
            if itens_rapid:
                return _normalizar_preview_nfe({
                    "source_type": "ocr",
                    "arquivo_origem": arquivo_origem,
                    "itens": itens_rapid,
                    "warnings": [
                        "OCR dos itens executado com RapidOCR. Revise codigo, descricao, quantidade e valor antes de confirmar a importacao.",
                        "Para melhor resultado, fotografe apenas a grade dos produtos.",
                    ],
                })
    except Exception:
        pass

    textos = _coletar_textos_ocr_itens_imagem(candidates, pytesseract)

    for texto in textos:
        linhas = [re.sub(r"\s+", " ", _as_str(l)).strip() for l in texto.splitlines() if _as_str(l).strip()]
        itens = _extrair_itens_ocr_linhas(linhas)
        if len(itens) > len(melhor_itens):
            melhor_itens = itens
        if len(itens) >= 2:
            break

    if not melhor_itens:
        raise ValueError("nenhum item foi identificado na foto. Tente enquadrar apenas a tabela dos produtos.")

    return _normalizar_preview_nfe({
        "source_type": "ocr",
        "arquivo_origem": arquivo_origem,
        "itens": melhor_itens,
        "warnings": [
            "OCR dos itens executado em modo de contingencia. Revise codigo, descricao, quantidade e valor antes de confirmar a importacao.",
            "Para melhor resultado, fotografe apenas a grade dos produtos.",
        ],
    })

def _azure_docint_value(field):
    field = field or {}
    if not isinstance(field, dict):
        return field
    for key in ("valueString", "valueNumber", "valueInteger", "valueDate", "content"):
        if field.get(key) not in (None, ""):
            return field.get(key)
    value_currency = field.get("valueCurrency")
    if isinstance(value_currency, dict) and value_currency.get("amount") not in (None, ""):
        return value_currency.get("amount")
    return ""

def _azure_docint_nfe_itens_preview(image_bytes, arquivo_origem=""):
    cfg = _carregar_nfe_config()
    if not cfg.get("azure_docint_habilitado"):
        raise ValueError("Azure Document Intelligence nao esta habilitado em Config > NF-e.")
    endpoint = _as_str(cfg.get("azure_docint_endpoint")).rstrip("/")
    api_key = _as_str(cfg.get("azure_docint_key"))
    model_id = _as_str(cfg.get("azure_docint_model_id")) or "prebuilt-invoice"
    api_version = _as_str(cfg.get("azure_docint_api_version")) or "2024-11-30"
    if not endpoint or not api_key:
        raise ValueError("Configure endpoint e chave do Azure Document Intelligence em Config > NF-e.")

    base_url = endpoint if endpoint.endswith("/documentintelligence") else f"{endpoint}/documentintelligence"
    analyze_url = f"{base_url}/documentModels/{model_id}:analyze?api-version={api_version}"
    headers = {
        "Ocp-Apim-Subscription-Key": api_key,
        "Content-Type": "application/octet-stream",
    }
    resp = requests.post(analyze_url, headers=headers, data=image_bytes, timeout=60)
    if resp.status_code not in (200, 202):
        try:
            detalhe = resp.json()
        except Exception:
            detalhe = resp.text
        raise RuntimeError(f"Azure Document Intelligence recusou a analise: {detalhe}")

    payload = resp.json() if resp.status_code == 200 else None
    operation_location = resp.headers.get("Operation-Location") or resp.headers.get("operation-location")
    if resp.status_code == 202:
        if not operation_location:
            raise RuntimeError("Azure nao retornou Operation-Location para acompanhar a analise.")
        inicio = time.time()
        while True:
            poll = requests.get(operation_location, headers={"Ocp-Apim-Subscription-Key": api_key}, timeout=30)
            payload = poll.json()
            status = _as_str(payload.get("status")).lower()
            if status == "succeeded":
                break
            if status == "failed":
                raise RuntimeError(f"Azure nao conseguiu analisar a imagem: {payload}")
            if (time.time() - inicio) > 120:
                raise RuntimeError("Azure demorou demais para concluir a analise da imagem.")
            time.sleep(1.5)

    analyze_result = payload.get("analyzeResult") if isinstance(payload, dict) else {}
    documentos = analyze_result.get("documents") if isinstance(analyze_result, dict) else []
    itens = []
    numero_nota = ""
    emitente_nome = ""
    data_emissao = ""

    if documentos:
        doc = documentos[0] if isinstance(documentos[0], dict) else {}
        campos = doc.get("fields") if isinstance(doc.get("fields"), dict) else {}
        numero_nota = _as_str(_azure_docint_value(campos.get("InvoiceId")))
        emitente_nome = _as_str(_azure_docint_value(campos.get("VendorName")))
        data_emissao = _normalizar_data_documento(_azure_docint_value(campos.get("InvoiceDate")))
        items_field = campos.get("Items") if isinstance(campos.get("Items"), dict) else {}
        value_array = items_field.get("valueArray") if isinstance(items_field, dict) else []
        for idx, raw in enumerate(value_array or [], start=1):
            value_object = raw.get("valueObject") if isinstance(raw, dict) else {}
            codigo = _as_str(_azure_docint_value(value_object.get("ProductCode") or value_object.get("ItemCode")))
            descricao = _as_str(_azure_docint_value(value_object.get("Description")))
            quantidade = _as_float_br(_azure_docint_value(value_object.get("Quantity")), _as_float(_azure_docint_value(value_object.get("Quantity")), 0.0))
            valor_unitario = _as_float_br(_azure_docint_value(value_object.get("UnitPrice")), _as_float(_azure_docint_value(value_object.get("UnitPrice")), 0.0))
            if not descricao and not codigo:
                continue
            itens.append({
                "item_seq": str(idx),
                "codigo_produto_nfe": codigo,
                "codigo_barras": "",
                "nome_produto": descricao,
                "unidade": "",
                "quantidade": quantidade,
                "valor_unitario": valor_unitario,
            })

    if not itens:
        raise ValueError("Azure analisou a imagem, mas nao retornou itens utilizaveis. Tente outra foto ou outro modelo.")

    return _aplicar_cadastro_embalagem_preview({
        "source_type": "ocr",
        "arquivo_origem": arquivo_origem or "Azure-Document-Intelligence",
        "numero_nota": numero_nota,
        "emitente_nome": emitente_nome,
        "data_emissao": data_emissao,
        "itens": itens,
        "warnings": [
            "Itens extraidos via Azure Document Intelligence. Revise os campos antes de confirmar a importacao.",
        ],
    })

def _preview_nfe_estoque_requisicao():
    payload = request.form.to_dict(flat=True) if request.form else (request.get_json(silent=True) or {})
    chave_acesso_esperada = _normalizar_chave_acesso_nfe(payload.get("chave_acesso_esperada"))
    conteudo, arquivo_origem, mimetype = _ler_arquivo_nfe_requisicao()
    if not conteudo:
        raise ValueError("envie um XML ou PDF da NF-e para importar")

    tipo_arquivo = _detectar_tipo_arquivo_nfe(conteudo, arquivo_origem=arquivo_origem, mimetype=mimetype)
    if tipo_arquivo == "xml":
        xml_text = _decode_xml_bytes(conteudo)
        preview = _preview_nfe_estoque_from_xml_text(
            xml_text,
            arquivo_origem=arquivo_origem,
            chave_acesso_esperada=chave_acesso_esperada,
        )
    elif tipo_arquivo == "html":
        html_text = _decode_xml_bytes(conteudo)
        preview = _parse_nfe_portal_html(html_text, arquivo_origem=arquivo_origem)
    elif tipo_arquivo == "pdf":
        preview = _parse_nfe_pdf_bytes(conteudo, arquivo_origem=arquivo_origem)
        chave_pdf = _normalizar_chave_acesso_nfe(preview.get("chave_acesso")) or chave_acesso_esperada
        if len(chave_pdf) == 44:
            nfe_status = _nfe_status_publico()
            if nfe_status.get("pronto_dfe"):
                try:
                    preview_dfe, resultado_dfe = _preview_nfe_estoque_por_dfe(
                        chave_pdf,
                        arquivo_origem="NFeDistribuicaoDFe",
                        warnings=[
                            "PDF usado apenas como contingencia para localizar a chave. Dados oficiais carregados do XML via DF-e."
                        ],
                    )
                    preview_dfe["arquivo_origem"] = (
                        f"{_as_str(arquivo_origem) or 'PDF'} -> NFeDistribuicaoDFe"
                    )
                    if bool(resultado_dfe.get("manifestado")):
                        preview_dfe["warnings"] = (
                            preview_dfe.get("warnings") or []
                        ) + ["XML liberado apos manifestacao automatica de ciencia da operacao."]
                    preview = _normalizar_preview_nfe(preview_dfe)
                except (RuntimeError, ValueError) as exc:
                    preview["warnings"] = (preview.get("warnings") or []) + [
                        f"Falha ao buscar o XML oficial pela chave do PDF: {str(exc)}. Mantido o PDF como contingencia."
                    ]
            else:
                preview["warnings"] = (preview.get("warnings") or []) + [
                    "A chave foi localizada no PDF, mas o DF-e nao esta pronto nesta configuracao. Mantido o PDF como contingencia."
                ]
    else:
        raise ValueError("formato nao suportado. Envie um XML ou PDF da NF-e.")

    chave_preview = _normalizar_chave_acesso_nfe(preview.get("chave_acesso"))
    if tipo_arquivo != "xml" and chave_acesso_esperada:
        if chave_preview and chave_preview != chave_acesso_esperada:
            raise ValueError("a chave bipada nao confere com o arquivo da NF-e informado")
        if not chave_preview:
            preview["chave_acesso"] = chave_acesso_esperada
            preview["warnings"] = (preview.get("warnings") or []) + [
                "A chave bipada foi aplicada ao rascunho porque o arquivo nao trouxe a chave automaticamente."
            ]
    return _aplicar_cadastro_embalagem_preview(preview)

def _persistir_preview_nfe_estoque(preview):
    nfe = _normalizar_preview_nfe(preview)
    chave_xml = _normalizar_chave_acesso_nfe(nfe.get("chave_acesso"))
    if chave_xml and len(chave_xml) != 44:
        raise ValueError("a chave de acesso da NF-e precisa ter 44 digitos ou ficar vazia")

    itens_validos = []
    for idx, item in enumerate(nfe.get("itens") or [], start=1):
        if not (
            _as_str(item.get("nome_produto"))
            or _as_str(item.get("codigo_produto_nfe"))
            or _as_str(item.get("codigo_barras"))
        ):
            continue
        quantidade = _as_float(item.get("quantidade"), 0.0)
        if quantidade <= 0:
            raise ValueError(f"o item {idx} precisa ter quantidade maior que zero")
        item_norm = _normalizar_item_preview_nfe(item, idx)
        if not _as_str(item_norm.get("nome_produto")):
            item_norm["nome_produto"] = _as_str(item_norm.get("codigo_produto_nfe")) or _as_str(item_norm.get("codigo_barras")) or f"Item {idx}"
        itens_validos.append(item_norm)

    if not itens_validos:
        raise ValueError("a NF-e precisa ter pelo menos um item valido para importar")

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        try:
            _validar_nota_duplicada_estoque(
                cur,
                numero_nota=_as_str(nfe.get("numero_nota")),
                chave_acesso_nfe=chave_xml,
                emitente_nome=_as_str(nfe.get("emitente_nome")),
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        conferencia_existente = None
        if chave_xml:
            cur.execute("SELECT id, status FROM estoque_conferencias WHERE chave_acesso=%s ORDER BY id DESC LIMIT 1", (chave_xml,))
            conferencia_existente = cur.fetchone()
            if conferencia_existente and _as_str(conferencia_existente.get("status")) == "consolidado":
                raise ValueError("esta NF-e ja foi consolidada no estoque")

        if conferencia_existente:
            conferencia_id = _as_int(conferencia_existente.get("id"), 0)
            cur.execute("""
                UPDATE estoque_conferencias
                SET
                    numero_nota=%s,
                    chave_acesso=%s,
                    serie=%s,
                    emitente_nome=%s,
                    emitente_cnpj=%s,
                    destinatario_nome=%s,
                    destinatario_cnpj=%s,
                    data_emissao=%s,
                    status='pendente',
                    arquivo_origem=%s,
                    confirmado_em=NULL,
                    recebido_por=''
                WHERE id=%s
            """, (
                _as_str(nfe.get("numero_nota")),
                chave_xml,
                _as_str(nfe.get("serie")),
                _as_str(nfe.get("emitente_nome")),
                _as_str(nfe.get("emitente_cnpj")),
                _as_str(nfe.get("destinatario_nome")),
                _as_str(nfe.get("destinatario_cnpj")),
                _as_str(nfe.get("data_emissao")),
                _as_str(nfe.get("arquivo_origem")),
                conferencia_id,
            ))
            cur.execute("DELETE FROM estoque_conferencia_itens WHERE conferencia_id=%s", (conferencia_id,))
        else:
            cur.execute("""
                INSERT INTO estoque_conferencias
                    (
                        numero_nota, chave_acesso, serie, emitente_nome, emitente_cnpj,
                        destinatario_nome, destinatario_cnpj, data_emissao, status, arquivo_origem
                    )
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, 'pendente', %s)
            """, (
                _as_str(nfe.get("numero_nota")),
                chave_xml,
                _as_str(nfe.get("serie")),
                _as_str(nfe.get("emitente_nome")),
                _as_str(nfe.get("emitente_cnpj")),
                _as_str(nfe.get("destinatario_nome")),
                _as_str(nfe.get("destinatario_cnpj")),
                _as_str(nfe.get("data_emissao")),
                _as_str(nfe.get("arquivo_origem")),
            ))
            conferencia_id = cur.lastrowid

        produtos_criados = 0
        source_type = _as_str(nfe.get("source_type")).lower()
        origem_cadastro = "nfe_pdf" if source_type == "pdf" else ("nfe_portal" if source_type == "portal" else "nfe_xml")
        for item in itens_validos:
            produto, criado = _obter_ou_criar_produto_estoque(
                cur,
                codigo_barras=item.get("codigo_barras"),
                codigo_produto_nfe=item.get("codigo_produto_nfe"),
                nome_produto=item.get("nome_produto"),
                unidade=item.get("unidade"),
                origem_cadastro=origem_cadastro,
            )
            if criado:
                produtos_criados += 1
            cur.execute("""
                INSERT INTO estoque_conferencia_itens
                    (
                        conferencia_id, item_seq, produto_id, codigo_produto_nfe, codigo_barras,
                        nome_produto, unidade, embalagem_tipo, quantidade_embalagem, fator_embalagem, fator_inferido,
                        quantidade_nfe, quantidade_conferida, valor_unitario
                    )
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                conferencia_id,
                _as_str(item.get("item_seq")),
                _as_int(produto.get("id"), 0) or None,
                _as_str(item.get("codigo_produto_nfe")),
                _normalizar_codigo_barras(item.get("codigo_barras")),
                _as_str(item.get("nome_produto")),
                _as_str(item.get("unidade")),
                _as_str(item.get("embalagem_tipo")) or _as_str(item.get("unidade")),
                _as_float(item.get("quantidade_embalagem"), _as_float(item.get("quantidade"), 0.0)),
                _as_float(item.get("fator_embalagem"), 1.0),
                1 if item.get("fator_inferido") in (True, 1, "1", "true", "True") else 0,
                _as_float(item.get("quantidade"), 0.0),
                _as_float(item.get("quantidade"), 0.0),
                _as_float(item.get("valor_unitario"), 0.0),
            ))

        conferencia = _carregar_conferencia_estoque(cur, conferencia_id)
        itens = _listar_itens_conferencia_estoque(cur, conferencia_id)
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {
        "conferencia": _estoque_conferencia_publica(conferencia),
        "itens": [_estoque_conferencia_item_publico(item) for item in itens],
        "produtos_criados": produtos_criados,
    }

def _resumir_nfe_para_abastecimento(nfe, combustivel_tipo=""):
    tipo_forcado = _as_str(combustivel_tipo).strip().lower()
    tipo_forcado = _normalizar_combustivel_tipo(tipo_forcado) if tipo_forcado else ""

    itens_tipados = []
    for item in nfe.get("itens") or []:
        tipo_item = _detectar_combustivel_tipo_item(item.get("nome_produto"))
        if tipo_item:
            itens_tipados.append((item, tipo_item))

    if tipo_forcado:
        selecionados = [item for item, tipo_item in itens_tipados if tipo_item == tipo_forcado]
        if not selecionados:
            raise ValueError(f"Nao foi encontrado item de {_combustivel_tipo_label(tipo_forcado).lower()} na NF-e informada.")
        tipo_final = tipo_forcado
    else:
        tipos_encontrados = sorted({tipo_item for _, tipo_item in itens_tipados})
        if not tipos_encontrados:
            raise ValueError("Nao foi possivel identificar diesel ou arla nos itens da NF-e.")
        if len(tipos_encontrados) > 1:
            raise ValueError("A NF-e possui mais de um tipo de combustivel. Informe se deseja importar diesel ou arla.")
        tipo_final = tipos_encontrados[0]
        selecionados = [item for item, _ in itens_tipados]

    quantidade_total = 0.0
    valor_total = 0.0
    for item in selecionados:
        quantidade_total += _as_float(item.get("quantidade"), 0.0)
        valor_total += _as_float(item.get("valor_total"), 0.0)

    if quantidade_total <= 0:
        raise ValueError("A NF-e informada nao possui quantidade valida para o combustivel selecionado.")

    return {
        "combustivel_tipo": tipo_final,
        "quantidade_litros": quantidade_total,
        "valor": valor_total,
        "numero_nota": _as_str(nfe.get("numero_nota")),
        "chave_acesso_nfe": _normalizar_chave_acesso_nfe(nfe.get("chave_acesso")),
        "emitente_nome": _as_str(nfe.get("emitente_nome")),
        "itens_encontrados": len(selecionados),
    }

def _importar_nfe_abastecimento_por_xml_text(abastecimento_id, xml_text, chave_acesso_esperada="", combustivel_tipo=""):
    chave_acesso_esperada = _normalizar_chave_acesso_nfe(chave_acesso_esperada)
    nfe = _parse_nfe_xml_text(xml_text)
    resumo_nfe = _resumir_nfe_para_abastecimento(nfe, combustivel_tipo=combustivel_tipo)

    chave_xml = _normalizar_chave_acesso_nfe(resumo_nfe.get("chave_acesso_nfe"))
    if chave_acesso_esperada and chave_xml != chave_acesso_esperada:
        raise ValueError("a chave bipada nao confere com o XML da NF-e informado")

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT
                a.id,
                a.veiculo_id,
                a.km,
                a.posto,
                a.status
            FROM abastecimentos a
            WHERE a.id=%s
        """, (abastecimento_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("abastecimento nao encontrado")

        status = _as_str(row.get("status")).lower()
        if status not in ("liberado", "abastecido"):
            raise ValueError("somente abastecimentos liberados ou abastecidos podem receber XML")

        _validar_nota_duplicada_abastecimento(
            cur,
            numero_nota=resumo_nfe.get("numero_nota"),
            chave_acesso_nfe=chave_xml,
            exclude_id=abastecimento_id,
        )

        valor = _as_float(resumo_nfe.get("valor"), 0.0)
        quantidade_litros = _as_float(resumo_nfe.get("quantidade_litros"), 0.0)
        if valor <= 0:
            raise ValueError("o XML informado nao trouxe valor valido para o combustivel selecionado")
        if quantidade_litros <= 0:
            raise ValueError("o XML informado nao trouxe quantidade valida para o combustivel selecionado")

        posto_final = _as_str(row.get("posto")) or _as_str(resumo_nfe.get("emitente_nome"))
        cur.execute("""
            UPDATE abastecimentos
            SET
                posto = %s,
                combustivel_tipo = %s,
                valor = %s,
                quantidade_litros = %s,
                chave_acesso_nfe = %s,
                numero_nota = %s,
                emitente_nome = %s,
                status = 'abastecido',
                data_abastecimento = NOW()
            WHERE id=%s
        """, (
            posto_final,
            resumo_nfe.get("combustivel_tipo"),
            valor,
            quantidade_litros,
            chave_xml,
            resumo_nfe.get("numero_nota"),
            resumo_nfe.get("emitente_nome"),
            abastecimento_id,
        ))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return resumo_nfe

def _buscar_produto_estoque(cur, codigo_barras="", codigo_produto_nfe="", nome_produto=""):
    codigo_barras = _normalizar_codigo_barras(codigo_barras)
    codigo_produto_nfe = _as_str(codigo_produto_nfe)
    nome_produto = _as_str(nome_produto)

    if codigo_barras:
        cur.execute("""
            SELECT id, codigo_barras, codigo_produto_nfe, nome_produto, unidade,
                   embalagem_tipo_padrao, fator_embalagem_padrao, origem_cadastro, criado_em, atualizado_em
            FROM estoque_produtos
            WHERE codigo_barras=%s
            ORDER BY id DESC
            LIMIT 1
        """, (codigo_barras,))
        row = cur.fetchone()
        if row:
            return row

    if codigo_produto_nfe:
        cur.execute("""
            SELECT id, codigo_barras, codigo_produto_nfe, nome_produto, unidade,
                   embalagem_tipo_padrao, fator_embalagem_padrao, origem_cadastro, criado_em, atualizado_em
            FROM estoque_produtos
            WHERE codigo_produto_nfe=%s
            ORDER BY id DESC
            LIMIT 1
        """, (codigo_produto_nfe,))
        row = cur.fetchone()
        if row:
            return row

    if nome_produto:
        cur.execute("""
            SELECT id, codigo_barras, codigo_produto_nfe, nome_produto, unidade,
                   embalagem_tipo_padrao, fator_embalagem_padrao, origem_cadastro, criado_em, atualizado_em
            FROM estoque_produtos
            WHERE nome_produto=%s
            ORDER BY id DESC
            LIMIT 1
        """, (nome_produto,))
        row = cur.fetchone()
        if row:
            return row

    return None

def _obter_ou_criar_produto_estoque(cur, codigo_barras="", codigo_produto_nfe="", nome_produto="", unidade="", origem_cadastro="manual"):
    row = _buscar_produto_estoque(
        cur,
        codigo_barras=codigo_barras,
        codigo_produto_nfe=codigo_produto_nfe,
        nome_produto=nome_produto,
    )
    if row:
        updates = []
        params = []
        codigo_barras = _normalizar_codigo_barras(codigo_barras)
        codigo_produto_nfe = _as_str(codigo_produto_nfe)
        unidade = _as_str(unidade)
        if codigo_barras and not _as_str(row.get("codigo_barras")):
            updates.append("codigo_barras=%s")
            params.append(codigo_barras)
        if codigo_produto_nfe and not _as_str(row.get("codigo_produto_nfe")):
            updates.append("codigo_produto_nfe=%s")
            params.append(codigo_produto_nfe)
        if unidade and not _as_str(row.get("unidade")):
            updates.append("unidade=%s")
            params.append(unidade)
        if updates:
            params.append(row.get("id"))
            cur.execute(f"UPDATE estoque_produtos SET {', '.join(updates)} WHERE id=%s", tuple(params))
            row = {
                **row,
                "codigo_barras": codigo_barras or row.get("codigo_barras"),
                "codigo_produto_nfe": codigo_produto_nfe or row.get("codigo_produto_nfe"),
                "unidade": unidade or row.get("unidade"),
            }
        return row, False

    cur.execute("""
        INSERT INTO estoque_produtos
            (codigo_barras, codigo_produto_nfe, nome_produto, unidade, embalagem_tipo_padrao, fator_embalagem_padrao, origem_cadastro)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s)
    """, (
        _normalizar_codigo_barras(codigo_barras),
        _as_str(codigo_produto_nfe),
        _as_str(nome_produto),
        _as_str(unidade),
        "",
        0.0,
        _as_str(origem_cadastro) or "manual",
    ))
    produto_id = cur.lastrowid
    return {
        "id": produto_id,
        "codigo_barras": _normalizar_codigo_barras(codigo_barras),
        "codigo_produto_nfe": _as_str(codigo_produto_nfe),
        "nome_produto": _as_str(nome_produto),
        "unidade": _as_str(unidade),
        "embalagem_tipo_padrao": "",
        "fator_embalagem_padrao": 0.0,
        "origem_cadastro": _as_str(origem_cadastro) or "manual",
    }, True

def _produto_estoque_publico(row):
    return {
        "id": _as_int(row.get("id"), 0),
        "codigo_barras": _normalizar_codigo_barras(row.get("codigo_barras")),
        "codigo_produto_nfe": _as_str(row.get("codigo_produto_nfe")),
        "nome_produto": _as_str(row.get("nome_produto")),
        "unidade": _as_str(row.get("unidade")),
        "embalagem_tipo_padrao": _as_str(row.get("embalagem_tipo_padrao")),
        "fator_embalagem_padrao": _as_float(row.get("fator_embalagem_padrao"), 0.0),
        "origem_cadastro": _as_str(row.get("origem_cadastro")) or "manual",
        "criado_em": _fmt_dt(row.get("criado_em")),
        "atualizado_em": _fmt_dt(row.get("atualizado_em")),
    }

def _aplicar_cadastro_embalagem_preview(preview):
    preview = _normalizar_preview_nfe(preview)
    itens = preview.get("itens") or []
    if not itens:
        return preview

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        itens_final = []
        for item in itens:
            cadastro = _buscar_produto_estoque(
                cur,
                codigo_barras=item.get("codigo_barras"),
                codigo_produto_nfe=item.get("codigo_produto_nfe"),
                nome_produto=item.get("nome_produto"),
            ) or {}
            unidade = _as_str(item.get("unidade"))
            if re.fullmatch(r"\d[\d.,]*", unidade or ""):
                unidade = ""
            embalagem_padrao = _as_str(cadastro.get("embalagem_tipo_padrao"))
            fator_padrao = _as_float(cadastro.get("fator_embalagem_padrao"), 0.0)
            item_atual = dict(item or {})
            if embalagem_padrao:
                item_atual["embalagem_tipo"] = embalagem_padrao
                if not unidade:
                    item_atual["unidade"] = embalagem_padrao
            else:
                item_atual["unidade"] = unidade
            if fator_padrao > 0 and _as_float(item_atual.get("fator_embalagem"), 0.0) <= 0:
                item_atual["fator_embalagem"] = fator_padrao
                item_atual["fator_inferido"] = 0
            itens_final.append(_normalizar_item_preview_nfe(item_atual, len(itens_final) + 1))
        preview["itens"] = itens_final
        return preview
    finally:
        cur.close()
        conn.close()

def _estoque_conferencia_publica(row):
    return {
        "id": _as_int(row.get("id"), 0),
        "numero_nota": _as_str(row.get("numero_nota")),
        "chave_acesso": _as_str(row.get("chave_acesso")),
        "serie": _as_str(row.get("serie")),
        "emitente_nome": _as_str(row.get("emitente_nome")),
        "emitente_cnpj": _as_str(row.get("emitente_cnpj")),
        "destinatario_nome": _as_str(row.get("destinatario_nome")),
        "destinatario_cnpj": _as_str(row.get("destinatario_cnpj")),
        "data_emissao": _as_str(row.get("data_emissao")),
        "status": _as_str(row.get("status")) or "pendente",
        "origem_setor": _as_str(row.get("origem_setor")) or "Fabrica",
        "destino_setor": _as_str(row.get("destino_setor")) or "Almoxarifado",
        "arquivo_origem": _as_str(row.get("arquivo_origem")),
        "recebido_por": _as_str(row.get("recebido_por")),
        "criado_em": _fmt_dt(row.get("criado_em")),
        "confirmado_em": _fmt_dt(row.get("confirmado_em")),
        "total_itens": _as_int(row.get("total_itens"), 0),
        "total_quantidade_nfe": _as_float(row.get("total_quantidade_nfe"), 0.0),
        "total_quantidade_conferida": _as_float(row.get("total_quantidade_conferida"), 0.0),
    }

def _estoque_conferencia_item_publico(row):
    return {
        "id": _as_int(row.get("id"), 0),
        "conferencia_id": _as_int(row.get("conferencia_id"), 0),
        "produto_id": _as_int(row.get("produto_id"), 0),
        "item_seq": _as_str(row.get("item_seq")),
        "codigo_produto_nfe": _as_str(row.get("codigo_produto_nfe")),
        "codigo_barras": _normalizar_codigo_barras(row.get("codigo_barras")),
        "nome_produto": _as_str(row.get("nome_produto")),
        "unidade": _as_str(row.get("unidade")),
        "embalagem_tipo": _as_str(row.get("embalagem_tipo")),
        "quantidade_embalagem": _as_float(row.get("quantidade_embalagem"), 0.0),
        "fator_embalagem": _as_float(row.get("fator_embalagem"), 1.0),
        "fator_inferido": 1 if row.get("fator_inferido") else 0,
        "quantidade_nfe": _as_float(row.get("quantidade_nfe"), 0.0),
        "quantidade_conferida": _as_float(row.get("quantidade_conferida"), 0.0),
        "valor_unitario": _as_float(row.get("valor_unitario"), 0.0),
        "estoque_movimento_id": _as_int(row.get("estoque_movimento_id"), 0),
        "consolidado_em": _fmt_dt(row.get("consolidado_em")),
    }

def _carregar_produto_estoque_por_id(cur, produto_id):
    produto_id = _as_int(produto_id, 0)
    if produto_id <= 0:
        return None
    cur.execute("""
        SELECT
            id,
            codigo_barras,
            codigo_produto_nfe,
            nome_produto,
            unidade,
            embalagem_tipo_padrao,
            fator_embalagem_padrao,
            origem_cadastro,
            criado_em,
            atualizado_em
        FROM estoque_produtos
        WHERE id=%s
        LIMIT 1
    """, (produto_id,))
    return cur.fetchone()

def _carregar_conferencia_estoque(cur, conferencia_id):
    cur.execute("""
        SELECT
            c.*,
            COUNT(i.id) AS total_itens,
            COALESCE(SUM(i.quantidade_nfe), 0) AS total_quantidade_nfe,
            COALESCE(SUM(i.quantidade_conferida), 0) AS total_quantidade_conferida
        FROM estoque_conferencias c
        LEFT JOIN estoque_conferencia_itens i ON i.conferencia_id = c.id
        WHERE c.id=%s
        GROUP BY c.id
        LIMIT 1
    """, (conferencia_id,))
    return cur.fetchone()

def _listar_itens_conferencia_estoque(cur, conferencia_id):
    cur.execute("""
        SELECT
            id,
            conferencia_id,
            produto_id,
            item_seq,
            codigo_produto_nfe,
            codigo_barras,
            nome_produto,
            unidade,
            embalagem_tipo,
            quantidade_embalagem,
            fator_embalagem,
            fator_inferido,
            quantidade_nfe,
            quantidade_conferida,
            valor_unitario,
            estoque_movimento_id,
            consolidado_em
        FROM estoque_conferencia_itens
        WHERE conferencia_id=%s
        ORDER BY CAST(COALESCE(NULLIF(item_seq, ''), '0') AS UNSIGNED), id ASC
    """, (conferencia_id,))
    return cur.fetchall() or []

def _usuario_ator_req():
    uid = _as_int(request.headers.get("X-Usuario-Id"), 0)
    nome = _as_str(request.headers.get("X-Usuario-Nome"))
    login = _as_str(request.headers.get("X-Usuario-Login"))
    bruto = _as_str(request.headers.get("X-Usuario-Logado"))
    if nome and login:
        return f"{nome} ({login})"
    if nome:
        return nome
    if login:
        return login
    if bruto:
        return bruto
    if uid > 0:
        return f"usuario_id:{uid}"
    return "desconhecido"

def _registrar_log_exclusao(cur, usuario, entidade, item_id, descricao):
    cur.execute(
        """
        INSERT INTO logs_exclusoes (usuario, entidade, item_id, descricao, data_evento)
        VALUES (%s, %s, %s, %s, NOW())
        """,
        (_as_str(usuario) or "desconhecido", _as_str(entidade), _as_int(item_id, 0), _as_str(descricao))
    )

FRETE_SELECT_SQL = """
    SELECT
        f.id,
        f.nome,
        f.cidade,
        f.data_carga,
        f.status,
        f.motorista_id,
        f.entregador_id,
        f.veiculo_id,
        f.carga_id,
        f.observacao,
        f.km_atual,
        f.peso,
        f.qtd_entregas,
        f.created_at,
        f.updated_at,
        f.finalizado_em,
        m.nome AS motorista_nome,
        e.nome AS entregador_nome,
        v.nome AS veiculo_nome,
        v.placa AS veiculo_placa,
        c.nome AS carga_nome
    FROM fretes f
    LEFT JOIN motoristas m ON f.motorista_id = m.id
    LEFT JOIN motoristas e ON f.entregador_id = e.id
    LEFT JOIN veiculos v ON f.veiculo_id = v.id
    LEFT JOIN cargas c ON f.carga_id = c.id
"""

def _serialize_frete_row(row):
    if not row:
        return None
    return {
        "id": _as_int(row.get("id"), 0),
        "nome": _as_str(row.get("nome")),
        "cidade": _as_str(row.get("cidade")),
        "data_carga": _fmt_date(row.get("data_carga") or row.get("created_at")),
        "status": _as_str(row.get("status")),
        "motorista_id": _as_int(row.get("motorista_id"), 0) or None,
        "entregador_id": _as_int(row.get("entregador_id"), 0) or None,
        "veiculo_id": _as_int(row.get("veiculo_id"), 0) or None,
        "carga_id": _as_int(row.get("carga_id"), 0) or None,
        "observacao": _as_str(row.get("observacao")),
        "km_atual": _as_int(row.get("km_atual"), 0),
        "peso": _as_float(row.get("peso"), 0.0),
        "qtd_entregas": _as_int(row.get("qtd_entregas"), 0),
        "motorista_nome": _as_str(row.get("motorista_nome")),
        "entregador_nome": _as_str(row.get("entregador_nome")),
        "veiculo_nome": _as_str(row.get("veiculo_nome")),
        "veiculo_placa": _as_str(row.get("veiculo_placa")),
        "carga_nome": _as_str(row.get("carga_nome")),
        "created_at": _fmt_dt(row.get("created_at")),
        "updated_at": _fmt_dt(row.get("updated_at")),
        "finalizado_em": _fmt_dt(row.get("finalizado_em")),
    }

def _buscar_frete_detalhado(cur, frete_id):
    cur.execute(FRETE_SELECT_SQL + " WHERE f.id = %s LIMIT 1", (frete_id,))
    row = cur.fetchone()
    return _serialize_frete_row(row) if row else None

def _frete_hist_val(v):
    s = _as_str(v)
    return s if s else "-"

def _frete_hist_num(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    return str(v)

def _montar_detalhes_historico_frete(acao, antes=None, depois=None):
    antes = antes or {}
    depois = depois or {}
    ref = depois or antes
    if acao == "criado":
        return (
            f"Frete {_frete_hist_val(ref.get('nome'))} criado | "
            f"Status {_frete_hist_val(ref.get('status'))} | "
            f"Veiculo {_frete_hist_val(ref.get('veiculo_nome'))} | "
            f"Entregas {_frete_hist_num(ref.get('qtd_entregas'))}"
        )
    if acao == "excluido":
        return (
            f"Frete {_frete_hist_val(ref.get('nome'))} excluido | "
            f"Status {_frete_hist_val(ref.get('status'))}"
        )
    if acao == "removido_automaticamente":
        return (
            f"Frete {_frete_hist_val(ref.get('nome'))} removido automaticamente "
            f"apos 1 dia em Finalizado."
        )

    campos = [
        ("nome", "Nome", _frete_hist_val),
        ("cidade", "Cidade", _frete_hist_val),
        ("data_carga", "Data carga", _frete_hist_val),
        ("status", "Status", _frete_hist_val),
        ("veiculo_nome", "Veiculo", _frete_hist_val),
        ("motorista_nome", "Motorista", _frete_hist_val),
        ("entregador_nome", "Entregador", _frete_hist_val),
        ("carga_nome", "Carga", _frete_hist_val),
        ("km_atual", "KM", _frete_hist_num),
        ("peso", "Peso", _frete_hist_num),
        ("qtd_entregas", "Entregas", _frete_hist_num),
        ("observacao", "Observacao", _frete_hist_val),
    ]
    mudancas = []
    for campo, label, fmt in campos:
        antigo = fmt(antes.get(campo))
        novo = fmt(depois.get(campo))
        if antigo != novo:
            mudancas.append(f"{label}: {antigo} -> {novo}")
    return "; ".join(mudancas[:6]) if mudancas else "Atualizacao sem mudancas visiveis."

def _registrar_historico_frete(cur, frete_id, acao, usuario, antes=None, depois=None):
    antes = antes or {}
    depois = depois or {}
    ref = depois or antes
    cur.execute(
        """
        INSERT INTO fretes_historico (
            frete_id, acao, usuario, frete_nome,
            status_anterior, status_novo,
            veiculo_nome, motorista_nome, entregador_nome,
            detalhes, dados_antes_json, dados_depois_json, criado_em
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """,
        (
            _as_int(frete_id, 0),
            _as_str(acao),
            _as_str(usuario) or "desconhecido",
            _as_str(ref.get("nome")),
            _as_str(antes.get("status")),
            _as_str((depois or antes).get("status")),
            _as_str(ref.get("veiculo_nome")),
            _as_str(ref.get("motorista_nome")),
            _as_str(ref.get("entregador_nome")),
            _montar_detalhes_historico_frete(acao, antes, depois),
            json.dumps(antes or {}, ensure_ascii=False),
            json.dumps(depois or {}, ensure_ascii=False),
        )
    )

def _limpar_fretes_finalizados_expirados():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    removidos = 0
    try:
        cur.execute(
            FRETE_SELECT_SQL + """
            WHERE f.status = 'retornando'
              AND f.finalizado_em IS NOT NULL
              AND f.finalizado_em <= DATE_SUB(NOW(), INTERVAL 1 DAY)
            ORDER BY f.finalizado_em ASC, f.id ASC
            """
        )
        expirados = [_serialize_frete_row(row) for row in (cur.fetchall() or [])]
        expirados = [item for item in expirados if item]
        for frete in expirados:
            cur.execute("DELETE FROM fretes_historico WHERE frete_id = %s", (frete["id"],))
            cur.execute("DELETE FROM fretes WHERE id = %s", (frete["id"],))
            descricao = (
                f"frete id={frete['id']} nome={_as_str(frete.get('nome'))} "
                f"status={_as_str(frete.get('status'))} removido automaticamente apos 1 dia finalizado"
            )
            _registrar_log_exclusao(cur, "sistema", "fretes", frete["id"], descricao)
            removidos += 1
        if removidos:
            conn.commit()
    finally:
        cur.close()
        conn.close()
    return removidos

def _as_bool(v, default=False):
    if v is None:
        return bool(default)
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "sim", "s", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "nao", "não", "n", "no", "off", ""):
        return False
    return bool(default)

SIP_RAMAL_BASE = 1000
SIP_RAMAL_LIMITE = 9999

def _senha_parece_hash(v):
    s = _as_str(v)
    if not s:
        return False
    if s.startswith(("scrypt:", "pbkdf2:", "argon2:", "$2a$", "$2b$", "$2y$", "$argon2")):
        return True
    return ":" in s and len(s) >= 40

def _sip_ramal_interno(v):
    s = _as_str(v)
    return s if len(s) == 4 and s.isdigit() else ""

def _calcular_ramais_sip(rows):
    usados = set()
    ramais = {}
    pendentes = []
    proximo = SIP_RAMAL_BASE
    for row in rows or []:
        user_id = _as_int(row.get("id"), 0)
        ramal = _sip_ramal_interno(row.get("sip_ramal"))
        if user_id <= 0:
            continue
        if ramal and ramal not in usados:
            usados.add(ramal)
            ramais[user_id] = ramal
        else:
            pendentes.append(user_id)
    for user_id in pendentes:
        while proximo <= SIP_RAMAL_LIMITE and f"{proximo:04d}" in usados:
            proximo += 1
        if proximo > SIP_RAMAL_LIMITE:
            break
        ramal = f"{proximo:04d}"
        usados.add(ramal)
        ramais[user_id] = ramal
        proximo += 1
    return ramais

def _listar_usuarios_sip(conn):
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT id, login, senha, sip_usuario, sip_senha, sip_ramal
            FROM usuarios
            ORDER BY id ASC
        """)
        return cur.fetchall() or []
    finally:
        cur.close()

def _sincronizar_usuarios_sip(conn, senha_plana_por_id=None, apenas_ids=None):
    rows = _listar_usuarios_sip(conn)
    if not rows:
        return 0
    password_hints = senha_plana_por_id or {}
    ids_filtrados = {int(i) for i in (apenas_ids or []) if _as_int(i, 0) > 0} if apenas_ids else None
    ramais = _calcular_ramais_sip(rows)
    cur = conn.cursor()
    atualizados = 0
    try:
        for row in rows:
            user_id = _as_int(row.get("id"), 0)
            if user_id <= 0:
                continue
            if ids_filtrados is not None and user_id not in ids_filtrados:
                continue

            sip_usuario_atual = _as_str(row.get("sip_usuario"))
            sip_senha_atual = _as_str(row.get("sip_senha"))
            sip_ramal_atual = _as_str(row.get("sip_ramal"))

            sip_usuario_final = sip_usuario_atual or _as_str(row.get("login"))
            sip_senha_final = sip_senha_atual
            if not sip_senha_final:
                sip_senha_final = _as_str(password_hints.get(user_id))
            if not sip_senha_final:
                senha_db = _as_str(row.get("senha"))
                if senha_db and not _senha_parece_hash(senha_db):
                    sip_senha_final = senha_db
            sip_ramal_final = ramais.get(user_id) or ""

            if (
                sip_usuario_final != sip_usuario_atual
                or sip_senha_final != sip_senha_atual
                or sip_ramal_final != sip_ramal_atual
            ):
                cur.execute(
                    """
                    UPDATE usuarios
                    SET sip_usuario=%s, sip_senha=%s, sip_ramal=%s
                    WHERE id=%s
                    """,
                    (sip_usuario_final, sip_senha_final, sip_ramal_final, user_id)
                )
                atualizados += 1
        return atualizados
    finally:
        cur.close()

def _freepbx_sync_config():
    return {
        "host": _as_str(_env("RB_FREEPBX_HOST", "")),
        "port": max(1, _env_int("RB_FREEPBX_SSH_PORT", 22)),
        "user": _as_str(_env("RB_FREEPBX_SSH_USER", "")),
        "password": _as_str(_env("RB_FREEPBX_SSH_PASS", "")),
        "timeout": max(5, _env_int("RB_FREEPBX_SSH_TIMEOUT", 20)),
        "transport": _as_str(_env("RB_FREEPBX_PJSIP_TRANSPORT", "0.0.0.0-wss")) or "0.0.0.0-wss",
        "allowed_codecs": _as_str(_env("RB_FREEPBX_PJSIP_ALLOW", "ulaw,alaw")) or "ulaw,alaw",
    }

def _freepbx_sync_enabled(cfg=None):
    cfg = cfg or _freepbx_sync_config()
    return bool(cfg.get("host") and cfg.get("user") and cfg.get("password"))

def _freepbx_listar_usuarios_sync(conn, apenas_ids=None):
    ids_filtrados = [int(i) for i in (apenas_ids or []) if _as_int(i, 0) > 0]
    cur = conn.cursor(dictionary=True)
    try:
        sql = """
            SELECT
                id,
                nome,
                login,
                ativo,
                sip_habilitado,
                sip_usuario,
                sip_senha,
                sip_ramal
            FROM usuarios
        """
        params = []
        if ids_filtrados:
            placeholders = ", ".join(["%s"] * len(ids_filtrados))
            sql += f" WHERE id IN ({placeholders})"
            params.extend(ids_filtrados)
        sql += " ORDER BY id ASC"
        cur.execute(sql, params)
        return cur.fetchall() or []
    finally:
        cur.close()

def _freepbx_sync_summary(results, reloaded=False, skipped_reason=""):
    summary = {
        "processed": len(results or []),
        "created": 0,
        "updated": 0,
        "converted": 0,
        "legacy_conflicts": 0,
        "skipped": 0,
        "errors": 0,
        "reloaded": bool(reloaded),
    }
    for item in results or []:
        status = _as_str(item.get("status"))
        if status in ("created", "updated", "converted"):
            summary[status] += 1
        elif status == "legacy_conflict":
            summary["legacy_conflicts"] += 1
        elif status == "error":
            summary["errors"] += 1
        else:
            summary["skipped"] += 1
    if skipped_reason:
        summary["skipped_reason"] = skipped_reason
    return summary

def _freepbx_prepare_sync_items(rows):
    itens = []
    resultados = []
    for row in rows or []:
        user_id = _as_int(row.get("id"), 0)
        login = _as_str(row.get("login"))
        nome = _as_str(row.get("nome")) or login or f"usuario {user_id}"
        ramal = _sip_ramal_interno(row.get("sip_ramal"))
        sip_usuario = _as_str(row.get("sip_usuario")) or login or ramal
        sip_senha = _as_str(row.get("sip_senha"))
        ativo = bool(_as_int(row.get("ativo"), 1))

        base = {
            "user_id": user_id,
            "login": login,
            "display_name": nome,
            "extension": ramal,
            "sip_username": sip_usuario,
        }

        if user_id <= 0:
            continue
        if not ativo:
            resultados.append({**base, "status": "skipped", "message": "Usuario inativo."})
            continue
        if not ramal:
            resultados.append({**base, "status": "skipped", "message": "Usuario sem ramal SIP valido de 4 digitos."})
            continue
        if not sip_usuario:
            resultados.append({**base, "status": "skipped", "message": "Usuario sem login SIP configurado."})
            continue
        if not sip_senha:
            resultados.append({**base, "status": "skipped", "message": "Usuario sem senha SIP configurada."})
            continue

        itens.append({
            **base,
            "secret": sip_senha,
            "allow_external": bool(_as_int(row.get("sip_habilitado"), 0)),
        })
    return itens, resultados

def _freepbx_sync_php_script(payload_b64):
    return f"""<?php
include "/etc/freepbx.conf";

$payload = json_decode(base64_decode('{payload_b64}'), true);
if (!is_array($payload)) {{
    fwrite(STDERR, "payload invalido\\n");
    exit(2);
}}

$core = FreePBX::Core();
$transport = trim((string)($payload['transport'] ?? '0.0.0.0-wss'));
$allowedCodecs = trim((string)($payload['allowed_codecs'] ?? 'ulaw,alaw'));
$convertLegacy = !empty($payload['convert_legacy']);
$items = is_array($payload['items'] ?? null) ? $payload['items'] : array();
$results = array();

foreach ($items as $item) {{
    $ext = trim((string)($item['extension'] ?? ''));
    $display = trim(str_replace(array('<', '>'), array('(', ')'), (string)($item['display_name'] ?? $item['login'] ?? $ext)));
    $sipUser = trim((string)($item['sip_username'] ?? $ext));
    $secret = (string)($item['secret'] ?? '');
    $forceConvert = !empty($item['force_convert']) || $convertLegacy;
    $base = array(
        'user_id' => (int)($item['user_id'] ?? 0),
        'login' => (string)($item['login'] ?? ''),
        'extension' => $ext,
        'sip_username' => $sipUser,
    );

    if (!preg_match('/^[0-9]{{4}}$/', $ext)) {{
        $results[] = $base + array('status' => 'skipped', 'message' => 'Ramal invalido.');
        continue;
    }}
    if ($sipUser === '') {{
        $results[] = $base + array('status' => 'skipped', 'message' => 'Usuario SIP vazio.');
        continue;
    }}
    if ($secret === '') {{
        $results[] = $base + array('status' => 'skipped', 'message' => 'Senha SIP vazia.');
        continue;
    }}

    $existingUser = $core->getUser($ext);
    $existingDevice = $core->getDevice($ext);
    $existingTech = strtolower((string)($existingDevice['tech'] ?? ''));
    $hadExisting = !empty($existingUser) || !empty($existingDevice);

    if ($hadExisting && $existingTech && $existingTech !== 'pjsip' && !$forceConvert) {{
        $results[] = $base + array(
            'status' => 'legacy_conflict',
            'message' => 'Ramal ja existe no FreePBX com tecnologia legada.',
            'existing_tech' => $existingTech,
        );
        continue;
    }}

    try {{
        if (!empty($existingDevice)) {{
            $core->delDevice($ext, true);
        }}
        if (!empty($existingUser)) {{
            $core->delUser($ext, true);
        }}

        $userSettings = $core->generateDefaultUserSettings($ext, $display);
        $userSettings['name'] = $display;
        $userSettings['password'] = $secret;
        $userSettings['outboundcid'] = sprintf('%s <%s>', $display, $ext);
        $userSettings['cid_masquerade'] = $ext;
        $core->addUser($ext, $userSettings, false);

        $deviceSettings = $core->generateDefaultDeviceSettings('pjsip', $ext, $display);
        $deviceSettings['secret']['value'] = $secret;
        $deviceSettings['username'] = array('value' => $sipUser, 'flag' => 500);
        $deviceSettings['defaultuser']['value'] = $sipUser;
        if ($transport !== '') {{
            $deviceSettings['transport']['value'] = $transport;
        }}
        $deviceSettings['allow']['value'] = $allowedCodecs;
        $deviceSettings['disallow']['value'] = 'all';
        $deviceSettings['dtmfmode']['value'] = 'auto';
        $deviceSettings['avpf']['value'] = 'yes';
        $deviceSettings['icesupport']['value'] = 'yes';
        $deviceSettings['webrtc']['value'] = 'yes';
        $deviceSettings['media_encryption']['value'] = 'dtls';
        $deviceSettings['media_encryption_optimistic']['value'] = 'no';
        $deviceSettings['media_use_received_transport']['value'] = 'yes';
        $deviceSettings['rtcp_mux']['value'] = 'yes';
        $deviceSettings['bundle']['value'] = 'yes';
        $deviceSettings['rewrite_contact']['value'] = 'yes';
        $deviceSettings['force_rport']['value'] = 'yes';
        $deviceSettings['rtp_symmetric']['value'] = 'yes';
        $deviceSettings['direct_media']['value'] = 'no';
        $deviceSettings['max_contacts']['value'] = '1';
        $deviceSettings['remove_existing']['value'] = 'yes';
        $deviceSettings['callerid']['value'] = sprintf('%s <%s>', $display, $ext);
        $core->addDevice($ext, 'pjsip', $deviceSettings, false);

        $status = 'created';
        if ($hadExisting) {{
            $status = ($existingTech && $existingTech !== 'pjsip') ? 'converted' : 'updated';
        }}
        $results[] = $base + array(
            'status' => $status,
            'message' => 'Ramal sincronizado no FreePBX.',
            'existing_tech' => $existingTech,
        );
    }} catch (Throwable $e) {{
        $results[] = $base + array(
            'status' => 'error',
            'message' => trim((string)$e->getMessage()) ?: 'Falha ao sincronizar no FreePBX.',
            'existing_tech' => $existingTech,
        );
    }}
}}

echo json_encode(array('results' => $results), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
"""

def _freepbx_ssh_exec(client, command, timeout=90):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err

def _freepbx_run_remote_sync(items, convert_legacy=False):
    cfg = _freepbx_sync_config()
    if not _freepbx_sync_enabled(cfg):
        raise RuntimeError("Configure RB_FREEPBX_SSH_USER e RB_FREEPBX_SSH_PASS para sincronizar ramais no FreePBX.")
    payload = {
        "convert_legacy": bool(convert_legacy),
        "transport": cfg.get("transport") or "0.0.0.0-wss",
        "allowed_codecs": cfg.get("allowed_codecs") or "ulaw,alaw",
        "items": items or [],
    }
    payload_b64 = base64.b64encode(json.dumps(payload, ensure_ascii=True).encode("utf-8")).decode("ascii")
    remote_path = f"/tmp/rb_freepbx_sync_{uuid.uuid4().hex}.php"
    script = _freepbx_sync_php_script(payload_b64)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sftp = None
    try:
        client.connect(
            cfg["host"],
            port=int(cfg["port"]),
            username=cfg["user"],
            password=cfg["password"],
            timeout=int(cfg["timeout"]),
            banner_timeout=int(cfg["timeout"]),
            auth_timeout=int(cfg["timeout"]),
        )
        sftp = client.open_sftp()
        remote_file = sftp.file(remote_path, "w")
        remote_file.write(script)
        remote_file.close()
        sftp.chmod(remote_path, 0o600)

        code, out, err = _freepbx_ssh_exec(client, f"php {remote_path}", timeout=max(120, int(cfg['timeout']) * 6))
        bruto = (out or "").strip()
        data = None
        if bruto:
            try:
                data = json.loads(bruto)
            except Exception:
                data = None
        if code != 0 and data is None:
            detalhe = (err or bruto or "").strip()
            raise RuntimeError(detalhe or "Falha ao executar sincronizacao no FreePBX.")
        if data is None:
            data = {}
        results = data.get("results") if isinstance(data, dict) else []
        if not isinstance(results, list):
            raise RuntimeError("Resposta invalida do FreePBX durante a sincronizacao.")

        reloaded = False
        if any(_as_str(item.get("status")) in ("created", "updated", "converted") for item in results):
            reload_timeout = max(120, int(cfg["timeout"]) * 9)
            code, out, err = _freepbx_ssh_exec(client, "fwconsole reload", timeout=reload_timeout)
            if code != 0:
                detalhe = (err or out or "").strip()
                raise RuntimeError(detalhe or "Falha ao aplicar configuracao no FreePBX.")
            reloaded = True
        return results, reloaded
    finally:
        try:
            if sftp is not None:
                sftp.remove(remote_path)
        except Exception:
            pass
        try:
            if sftp is not None:
                sftp.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass

def _freepbx_delete_php_script(extensions_b64):
    return f"""<?php
include "/etc/freepbx.conf";

$payload = json_decode(base64_decode('{extensions_b64}'), true);
$extensions = is_array($payload['extensions'] ?? null) ? $payload['extensions'] : array();
$results = array();
$core = FreePBX::Core();

foreach ($extensions as $rawExt) {{
    $ext = trim((string)$rawExt);
    if (!preg_match('/^[0-9]{{4}}$/', $ext)) {{
        $results[] = array(
            'extension' => $ext,
            'status' => 'skipped',
            'message' => 'Ramal invalido.',
        );
        continue;
    }}

    $existingUser = $core->getUser($ext);
    $existingDevice = $core->getDevice($ext);
    $existingTech = strtolower((string)($existingDevice['tech'] ?? ''));
    if (empty($existingUser) && empty($existingDevice)) {{
        $results[] = array(
            'extension' => $ext,
            'status' => 'skipped',
            'message' => 'Ramal nao encontrado no FreePBX.',
            'existing_tech' => $existingTech,
        );
        continue;
    }}

    try {{
        if (!empty($existingDevice)) {{
            $core->delDevice($ext, true);
        }}
        if (!empty($existingUser)) {{
            $core->delUser($ext, true);
        }}
        $results[] = array(
            'extension' => $ext,
            'status' => 'removed',
            'message' => 'Ramal removido do FreePBX.',
            'existing_tech' => $existingTech,
        );
    }} catch (Throwable $e) {{
        $results[] = array(
            'extension' => $ext,
            'status' => 'error',
            'message' => trim((string)$e->getMessage()) ?: 'Falha ao remover ramal no FreePBX.',
            'existing_tech' => $existingTech,
        );
    }}
}}

echo json_encode(array('results' => $results), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
"""

def _freepbx_run_remote_remove_extensions(extensions):
    cfg = _freepbx_sync_config()
    if not _freepbx_sync_enabled(cfg):
        raise RuntimeError("Configure RB_FREEPBX_SSH_USER e RB_FREEPBX_SSH_PASS para sincronizar ramais no FreePBX.")

    extensoes = []
    vistos = set()
    for raw in extensions or []:
        ext = _sip_ramal_interno(raw)
        if not ext or ext in vistos:
            continue
        vistos.add(ext)
        extensoes.append(ext)
    if not extensoes:
        return [], False

    payload_b64 = base64.b64encode(json.dumps({"extensions": extensoes}, ensure_ascii=True).encode("utf-8")).decode("ascii")
    remote_path = f"/tmp/rb_freepbx_remove_{uuid.uuid4().hex}.php"
    script = _freepbx_delete_php_script(payload_b64)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sftp = None
    try:
        client.connect(
            cfg["host"],
            port=int(cfg["port"]),
            username=cfg["user"],
            password=cfg["password"],
            timeout=int(cfg["timeout"]),
            banner_timeout=int(cfg["timeout"]),
            auth_timeout=int(cfg["timeout"]),
        )
        sftp = client.open_sftp()
        remote_file = sftp.file(remote_path, "w")
        remote_file.write(script)
        remote_file.close()
        sftp.chmod(remote_path, 0o600)

        code, out, err = _freepbx_ssh_exec(client, f"php {remote_path}", timeout=max(120, int(cfg['timeout']) * 6))
        bruto = (out or "").strip()
        data = None
        if bruto:
            try:
                data = json.loads(bruto)
            except Exception:
                data = None
        if code != 0 and data is None:
            detalhe = (err or bruto or "").strip()
            raise RuntimeError(detalhe or "Falha ao remover ramais no FreePBX.")
        if data is None:
            data = {}
        results = data.get("results") if isinstance(data, dict) else []
        if not isinstance(results, list):
            raise RuntimeError("Resposta invalida do FreePBX durante a remocao de ramais.")

        reloaded = False
        if any(_as_str(item.get("status")) == "removed" for item in results):
            reload_timeout = max(120, int(cfg["timeout"]) * 9)
            code, out, err = _freepbx_ssh_exec(client, "fwconsole reload", timeout=reload_timeout)
            if code != 0:
                detalhe = (err or out or "").strip()
                raise RuntimeError(detalhe or "Falha ao aplicar configuracao no FreePBX.")
            reloaded = True
        return results, reloaded
    finally:
        try:
            if sftp is not None:
                sftp.remove(remote_path)
        except Exception:
            pass
        try:
            if sftp is not None:
                sftp.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass

def _freepbx_ramais_sem_uso(extensoes):
    candidatos = []
    vistos = set()
    for raw in extensoes or []:
        ext = _sip_ramal_interno(raw)
        if not ext or ext in vistos:
            continue
        vistos.add(ext)
        candidatos.append(ext)
    if not candidatos:
        return []

    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        livres = []
        for ext in candidatos:
            cur.execute("SELECT COUNT(*) FROM usuarios WHERE sip_ramal=%s", (ext,))
            row = cur.fetchone()
            total = int(row[0]) if row else 0
            if total <= 0:
                livres.append(ext)
        return livres
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

def _sincronizar_usuarios_freepbx(apenas_ids=None, convert_legacy=False, strict=False):
    conn = None
    try:
        conn = get_conn()
        rows = _freepbx_listar_usuarios_sync(conn, apenas_ids=apenas_ids)
    finally:
        if conn is not None:
            conn.close()

    itens, resultados = _freepbx_prepare_sync_items(rows)
    if not itens:
        return {
            "results": resultados,
            "summary": _freepbx_sync_summary(resultados),
        }

    cfg = _freepbx_sync_config()
    if not _freepbx_sync_enabled(cfg):
        if strict:
            raise RuntimeError("Preencha RB_FREEPBX_SSH_USER e RB_FREEPBX_SSH_PASS no ambiente da aplicacao para sincronizar com o FreePBX.")
        return {
            "results": resultados,
            "summary": _freepbx_sync_summary(resultados, skipped_reason="credenciais_freepbx_ausentes"),
        }

    remotos, reloaded = _freepbx_run_remote_sync(itens, convert_legacy=convert_legacy)
    todos = resultados + (remotos or [])
    return {
        "results": todos,
        "summary": _freepbx_sync_summary(todos, reloaded=reloaded),
    }

def _sincronizar_usuario_freepbx_best_effort(user_id, convert_legacy=False, remove_extensions=None):
    user_id = _as_int(user_id, 0)
    if user_id <= 0:
        return
    extensoes_para_remover = _freepbx_ramais_sem_uso(remove_extensions or [])
    def _job():
        try:
            _sincronizar_usuarios_freepbx(apenas_ids=[user_id], convert_legacy=convert_legacy, strict=False)
            if extensoes_para_remover:
                _freepbx_run_remote_remove_extensions(extensoes_para_remover)
        except Exception as exc:
            print(f"WARN freepbx sync user {user_id}:", exc)

    try:
        threading.Thread(
            target=_job,
            name=f"freepbx-sync-{user_id}",
            daemon=True,
        ).start()
    except Exception:
        _job()

def _sip_profile_defaults():
    return {
        "ws_url": "",
        "dominio": "",
        "registrar_server": "",
        "outbound_proxy": "",
        "prefixo_saida": "",
        "caller_id_template": "{nome} RioBranco",
        "stun_servers": "",
        "turn_url": "",
        "turn_usuario": "",
        "turn_senha": "",
        "auto_register": True,
    }

def _sip_profile_publico(src):
    base = _sip_profile_defaults()
    if src:
        base.update({
            "ws_url": _as_str(src.get("ws_url")),
            "dominio": _as_str(src.get("dominio")),
            "registrar_server": _as_str(src.get("registrar_server")),
            "outbound_proxy": _as_str(src.get("outbound_proxy")),
            "prefixo_saida": _as_str(src.get("prefixo_saida")),
            "caller_id_template": _as_str(src.get("caller_id_template")) or "{nome} RioBranco",
            "stun_servers": _as_str(src.get("stun_servers")),
            "turn_url": _as_str(src.get("turn_url")),
            "turn_usuario": _as_str(src.get("turn_usuario")),
            "turn_senha": _as_str(src.get("turn_senha")),
            "auto_register": _as_bool(src.get("auto_register"), True),
        })
    return base

def _sip_config_defaults():
    return {
        "habilitado": False,
        "modo_ativo": "freepbx",
        "setevoip_direto": _sip_profile_defaults(),
        "freepbx": _sip_profile_defaults(),
        "updated_at": None,
    }

def _nfe_consulta_url_default():
    return "https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=completa&tipoConteudo=XbSeqxE8pl8="

NFE_UF_CODES = {
    "RO": "11",
    "AC": "12",
    "AM": "13",
    "RR": "14",
    "PA": "15",
    "AP": "16",
    "TO": "17",
    "MA": "21",
    "PI": "22",
    "CE": "23",
    "RN": "24",
    "PB": "25",
    "PE": "26",
    "AL": "27",
    "SE": "28",
    "BA": "29",
    "MG": "31",
    "ES": "32",
    "RJ": "33",
    "SP": "35",
    "PR": "41",
    "SC": "42",
    "RS": "43",
    "MS": "50",
    "MT": "51",
    "GO": "52",
    "DF": "53",
}
NFE_UF_CODES_REV = {codigo: uf for uf, codigo in NFE_UF_CODES.items()}

def _nfe_normalizar_ambiente(v):
    ambiente = _as_str(v).strip().lower()
    if ambiente in ("2", "homologacao", "homologacao ", "hom"):
        return "homologacao"
    return "producao"

def _nfe_normalizar_uf_autor(v):
    uf = _as_str(v).strip().upper()
    if uf in NFE_UF_CODES:
        return uf
    digits = re.sub(r"\D+", "", uf)
    return NFE_UF_CODES_REV.get(digits[:2], "")

def _nfe_cuf_autor(v):
    return NFE_UF_CODES.get(_nfe_normalizar_uf_autor(v), "")

def _nfe_config_defaults():
    return {
        "habilitado": False,
        "modo_ativo": "portal_assistido",
        "ambiente": "producao",
        "consulta_url": _nfe_consulta_url_default(),
        "abrir_portal_ao_bipar": True,
        "bloquear_notas_duplicadas": True,
        "destinatario_cnpj": "",
        "uf_autor": "",
        "certificado_arquivo": "",
        "certificado_senha": "",
        "ultimo_nsu": "",
        "auto_manifestar_ciencia": True,
        "azure_docint_habilitado": False,
        "azure_docint_endpoint": "",
        "azure_docint_key": "",
        "azure_docint_key_configurada": False,
        "azure_docint_model_id": "prebuilt-invoice",
        "azure_docint_api_version": "2024-11-30",
        "updated_at": None,
    }

def _nfe_mode_label(modo):
    return "Portal assistido (reCAPTCHA)" if _as_str(modo).lower() == "portal_assistido" else "Certificado digital / DF-e"

def _nfe_config_publico(row):
    base = _nfe_config_defaults()
    if not row:
        return base

    modo_ativo = _as_str(row.get("modo_ativo")).lower()
    if modo_ativo not in ("portal_assistido", "certificado_digital"):
        modo_ativo = "portal_assistido"

    base.update({
        "habilitado": bool(_as_int(row.get("habilitado"), 0)),
        "modo_ativo": modo_ativo,
        "ambiente": _nfe_normalizar_ambiente(row.get("ambiente")),
        "consulta_url": _as_str(row.get("consulta_url")) or _nfe_consulta_url_default(),
        "abrir_portal_ao_bipar": bool(_as_int(row.get("abrir_portal_ao_bipar"), 0)),
        "bloquear_notas_duplicadas": bool(_as_int(row.get("bloquear_notas_duplicadas"), 0)),
        "destinatario_cnpj": _as_str(row.get("destinatario_cnpj")),
        "uf_autor": _nfe_normalizar_uf_autor(row.get("uf_autor")),
        "certificado_arquivo": _as_str(row.get("certificado_arquivo")),
        "certificado_senha": _as_str(row.get("certificado_senha")),
        "ultimo_nsu": re.sub(r"\D+", "", _as_str(row.get("ultimo_nsu"))),
        "auto_manifestar_ciencia": bool(_as_int(row.get("auto_manifestar_ciencia"), 1)),
        "azure_docint_habilitado": bool(_as_int(row.get("azure_docint_habilitado"), 0)),
        "azure_docint_endpoint": _as_str(row.get("azure_docint_endpoint")),
        "azure_docint_key": _as_str(row.get("azure_docint_key")),
        "azure_docint_key_configurada": bool(_as_str(row.get("azure_docint_key"))),
        "azure_docint_model_id": _as_str(row.get("azure_docint_model_id")) or "prebuilt-invoice",
        "azure_docint_api_version": _as_str(row.get("azure_docint_api_version")) or "2024-11-30",
        "updated_at": _fmt_dt(row.get("updated_at")),
    })
    return base

def _sip_config_publico(row):
    base = _sip_config_defaults()
    if not row:
        return base

    legacy_profile = _sip_profile_publico(row)
    setevoip_profile = _sip_profile_publico(_json_obj_or_empty(row.get("setevoip_config_json")))
    freepbx_json = _json_obj_or_empty(row.get("freepbx_config_json"))
    freepbx_profile = _sip_profile_publico(freepbx_json if freepbx_json else legacy_profile)

    modo_ativo = _as_str(row.get("modo_ativo")).lower()
    if modo_ativo not in ("setevoip_direto", "freepbx"):
        modo_ativo = "freepbx"

    base.update({
        "habilitado": bool(_as_int(row.get("habilitado"), 0)),
        "modo_ativo": modo_ativo,
        "setevoip_direto": setevoip_profile,
        "freepbx": freepbx_profile,
        "updated_at": _fmt_dt(row.get("updated_at")),
    })
    return base

def _sip_profile_from_payload(payload):
    return _sip_profile_publico(payload or {})

def _sip_profile_from_env(prefix):
    return _sip_profile_publico({
        "ws_url": _env(f"{prefix}_WS_URL", ""),
        "dominio": _env(f"{prefix}_DOMINIO", ""),
        "registrar_server": _env(f"{prefix}_REGISTRAR_SERVER", ""),
        "outbound_proxy": _env(f"{prefix}_OUTBOUND_PROXY", ""),
        "prefixo_saida": _env(f"{prefix}_PREFIXO_SAIDA", ""),
        "caller_id_template": _env(f"{prefix}_CALLER_ID_TEMPLATE", "{nome} RioBranco"),
        "stun_servers": _env(f"{prefix}_STUN_SERVERS", ""),
        "turn_url": _env(f"{prefix}_TURN_URL", ""),
        "turn_usuario": _env(f"{prefix}_TURN_USUARIO", ""),
        "turn_senha": _env(f"{prefix}_TURN_SENHA", ""),
        "auto_register": _as_bool(_env(f"{prefix}_AUTO_REGISTER", "1"), True),
    })

def _sip_config_from_env():
    modo_ativo = _as_str(_env("RB_SIP_MODO_ATIVO", "freepbx")).lower()
    if modo_ativo not in ("setevoip_direto", "freepbx"):
        modo_ativo = "freepbx"
    return {
        "habilitado": _as_bool(_env("RB_SIP_HABILITADO", "0"), False),
        "modo_ativo": modo_ativo,
        "setevoip_direto": _sip_profile_from_env("RB_SIP_SETEVOIP"),
        "freepbx": _sip_profile_from_env("RB_SIP_FREEPBX"),
        "updated_at": None,
    }

def _sip_profile_has_signal(profile):
    if not profile:
        return False
    keys = (
        "ws_url",
        "dominio",
        "registrar_server",
        "outbound_proxy",
        "prefixo_saida",
        "stun_servers",
        "turn_url",
        "turn_usuario",
        "turn_senha",
    )
    return any(_as_str(profile.get(key)).strip() for key in keys)

def _sip_config_is_blank(cfg):
    if not cfg:
        return True
    if _as_bool(cfg.get("habilitado"), False):
        return False
    return not (
        _sip_profile_has_signal(cfg.get("setevoip_direto") or {})
        or _sip_profile_has_signal(cfg.get("freepbx") or {})
    )

def _sip_mode_label(modo):
    return "SeteVoIP Direto" if _as_str(modo).lower() == "setevoip_direto" else "FreePBX"

def _sip_endpoint_from_ws_url(ws_url):
    raw = _as_str(ws_url)
    if not raw:
        return {"host": "", "port": None, "scheme": ""}

    candidate = raw if "://" in raw else f"wss://{raw}"
    try:
        parsed = urlparse(candidate)
    except Exception:
        return {"host": "", "port": None, "scheme": ""}

    scheme = _as_str(parsed.scheme).lower() or "wss"
    host = _as_str(parsed.hostname)
    port = parsed.port or (443 if scheme == "wss" else 80)
    return {"host": host, "port": port, "scheme": scheme}

def _sip_status_publico():
    try:
        cfg = _carregar_sip_config()
    except Exception:
        cfg = _sip_config_defaults()

    modo = _as_str(cfg.get("modo_ativo")).lower()
    if modo not in ("setevoip_direto", "freepbx"):
        modo = "freepbx"

    perfil = cfg.get(modo) or {}
    ws_url = _as_str(perfil.get("ws_url"))
    dominio = _as_str(perfil.get("dominio"))
    endpoint = _sip_endpoint_from_ws_url(ws_url)
    host = _as_str(endpoint.get("host"))
    port = endpoint.get("port")

    return {
        "habilitado": bool(cfg.get("habilitado")),
        "modo_ativo": modo,
        "modo_label": _sip_mode_label(modo),
        "configurado": bool(ws_url and dominio),
        "ws_url": ws_url,
        "dominio": dominio,
        "endpoint_host": host,
        "endpoint_port": port,
        "endpoint_scheme": _as_str(endpoint.get("scheme")),
        "endpoint_online": bool(host and port and _tcp_open(host, port, timeout=1.5)),
    }

def _carregar_sip_config(cur=None):
    own_conn = None
    own_cur = cur
    try:
        if own_cur is None:
            own_conn = get_conn()
            own_cur = own_conn.cursor(dictionary=True)
        own_cur.execute("""
            SELECT
                id,
                habilitado,
                modo_ativo,
                setevoip_config_json,
                freepbx_config_json,
                ws_url,
                dominio,
                registrar_server,
                outbound_proxy,
                prefixo_saida,
                caller_id_template,
                stun_servers,
                turn_url,
                turn_usuario,
                turn_senha,
                auto_register,
                updated_at
            FROM sip_config
            WHERE id = 1
            LIMIT 1
        """)
        row = own_cur.fetchone() or {}
        return _sip_config_publico(row)
    finally:
        if own_cur is not None and own_cur is not cur:
            try:
                own_cur.close()
            except Exception:
                pass
        if own_conn is not None:
            try:
                own_conn.close()
            except Exception:
                pass

def _persistir_sip_config(habilitado, modo_ativo, setevoip_cfg, freepbx_cfg):
    modo = _as_str(modo_ativo).lower()
    if modo not in ("setevoip_direto", "freepbx"):
        modo = "freepbx"

    sete_cfg = _sip_profile_from_payload(setevoip_cfg)
    free_cfg = _sip_profile_from_payload(freepbx_cfg)
    perfil_ativo = sete_cfg if modo == "setevoip_direto" else free_cfg

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            INSERT INTO sip_config (
                id, habilitado, modo_ativo, setevoip_config_json, freepbx_config_json,
                ws_url, dominio, registrar_server, outbound_proxy,
                prefixo_saida, caller_id_template, stun_servers, turn_url, turn_usuario, turn_senha,
                auto_register, updated_at
            ) VALUES (
                1, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, NOW()
            )
            ON DUPLICATE KEY UPDATE
                habilitado = VALUES(habilitado),
                modo_ativo = VALUES(modo_ativo),
                setevoip_config_json = VALUES(setevoip_config_json),
                freepbx_config_json = VALUES(freepbx_config_json),
                ws_url = VALUES(ws_url),
                dominio = VALUES(dominio),
                registrar_server = VALUES(registrar_server),
                outbound_proxy = VALUES(outbound_proxy),
                prefixo_saida = VALUES(prefixo_saida),
                caller_id_template = VALUES(caller_id_template),
                stun_servers = VALUES(stun_servers),
                turn_url = VALUES(turn_url),
                turn_usuario = VALUES(turn_usuario),
                turn_senha = VALUES(turn_senha),
                auto_register = VALUES(auto_register),
                updated_at = NOW()
        """, (
            1 if _as_bool(habilitado, False) else 0,
            modo,
            json.dumps(sete_cfg, ensure_ascii=False),
            json.dumps(free_cfg, ensure_ascii=False),
            perfil_ativo.get("ws_url", ""),
            perfil_ativo.get("dominio", ""),
            perfil_ativo.get("registrar_server", ""),
            perfil_ativo.get("outbound_proxy", ""),
            perfil_ativo.get("prefixo_saida", ""),
            perfil_ativo.get("caller_id_template", "{nome} RioBranco"),
            perfil_ativo.get("stun_servers", ""),
            perfil_ativo.get("turn_url", ""),
            perfil_ativo.get("turn_usuario", ""),
            perfil_ativo.get("turn_senha", ""),
            1 if bool(perfil_ativo.get("auto_register", True)) else 0,
        ))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return _carregar_sip_config()

def _carregar_nfe_config(cur=None):
    own_conn = None
    own_cur = cur
    try:
        if own_cur is None:
            own_conn = get_conn()
            own_cur = own_conn.cursor(dictionary=True)
        own_cur.execute("""
            SELECT
                id,
                habilitado,
                modo_ativo,
                ambiente,
                consulta_url,
                abrir_portal_ao_bipar,
                bloquear_notas_duplicadas,
                destinatario_cnpj,
                uf_autor,
                certificado_arquivo,
                certificado_senha,
                ultimo_nsu,
                auto_manifestar_ciencia,
                azure_docint_habilitado,
                azure_docint_endpoint,
                azure_docint_key,
                azure_docint_model_id,
                azure_docint_api_version,
                updated_at
            FROM nfe_config
            WHERE id = 1
            LIMIT 1
        """)
        row = own_cur.fetchone() or {}
        return _nfe_config_publico(row)
    finally:
        if own_cur is not None and own_cur is not cur:
            try:
                own_cur.close()
            except Exception:
                pass
        if own_conn is not None:
            try:
                own_conn.close()
            except Exception:
                pass

def _persistir_nfe_config(data):
    modo = _as_str(data.get("modo_ativo")).lower()
    if modo not in ("portal_assistido", "certificado_digital"):
        modo = "portal_assistido"

    consulta_url = _as_str(data.get("consulta_url")) or _nfe_consulta_url_default()
    payload = {
        "habilitado": 1 if _as_bool(data.get("habilitado"), False) else 0,
        "modo_ativo": modo,
        "ambiente": _nfe_normalizar_ambiente(data.get("ambiente")),
        "consulta_url": consulta_url,
        "abrir_portal_ao_bipar": 1 if _as_bool(data.get("abrir_portal_ao_bipar"), True) else 0,
        "bloquear_notas_duplicadas": 1 if _as_bool(data.get("bloquear_notas_duplicadas"), True) else 0,
        "destinatario_cnpj": _as_str(data.get("destinatario_cnpj")),
        "uf_autor": _nfe_normalizar_uf_autor(data.get("uf_autor")),
        "certificado_arquivo": _as_str(data.get("certificado_arquivo")),
        "certificado_senha": _as_str(data.get("certificado_senha")),
        "ultimo_nsu": re.sub(r"\D+", "", _as_str(data.get("ultimo_nsu"))),
        "auto_manifestar_ciencia": 1 if _as_bool(data.get("auto_manifestar_ciencia"), True) else 0,
        "azure_docint_habilitado": 1 if _as_bool(data.get("azure_docint_habilitado"), False) else 0,
        "azure_docint_endpoint": _as_str(data.get("azure_docint_endpoint")).rstrip("/"),
        "azure_docint_key": _as_str(data.get("azure_docint_key")),
        "azure_docint_model_id": _as_str(data.get("azure_docint_model_id")) or "prebuilt-invoice",
        "azure_docint_api_version": _as_str(data.get("azure_docint_api_version")) or "2024-11-30",
    }

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO nfe_config (
                id, habilitado, modo_ativo, ambiente, consulta_url, abrir_portal_ao_bipar,
                bloquear_notas_duplicadas, destinatario_cnpj, uf_autor, certificado_arquivo,
                certificado_senha, ultimo_nsu, auto_manifestar_ciencia,
                azure_docint_habilitado, azure_docint_endpoint, azure_docint_key,
                azure_docint_model_id, azure_docint_api_version, updated_at
            ) VALUES (
                1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            ON DUPLICATE KEY UPDATE
                habilitado = VALUES(habilitado),
                modo_ativo = VALUES(modo_ativo),
                ambiente = VALUES(ambiente),
                consulta_url = VALUES(consulta_url),
                abrir_portal_ao_bipar = VALUES(abrir_portal_ao_bipar),
                bloquear_notas_duplicadas = VALUES(bloquear_notas_duplicadas),
                destinatario_cnpj = VALUES(destinatario_cnpj),
                uf_autor = VALUES(uf_autor),
                certificado_arquivo = VALUES(certificado_arquivo),
                certificado_senha = VALUES(certificado_senha),
                ultimo_nsu = VALUES(ultimo_nsu),
                auto_manifestar_ciencia = VALUES(auto_manifestar_ciencia),
                azure_docint_habilitado = VALUES(azure_docint_habilitado),
                azure_docint_endpoint = VALUES(azure_docint_endpoint),
                azure_docint_key = VALUES(azure_docint_key),
                azure_docint_model_id = VALUES(azure_docint_model_id),
                azure_docint_api_version = VALUES(azure_docint_api_version),
                updated_at = NOW()
        """, (
            payload["habilitado"],
            payload["modo_ativo"],
            payload["ambiente"],
            payload["consulta_url"],
            payload["abrir_portal_ao_bipar"],
            payload["bloquear_notas_duplicadas"],
            payload["destinatario_cnpj"],
            payload["uf_autor"],
            payload["certificado_arquivo"],
            payload["certificado_senha"],
            payload["ultimo_nsu"],
            payload["auto_manifestar_ciencia"],
            payload["azure_docint_habilitado"],
            payload["azure_docint_endpoint"],
            payload["azure_docint_key"],
            payload["azure_docint_model_id"],
            payload["azure_docint_api_version"],
        ))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return _carregar_nfe_config()

def _nfe_status_publico():
    try:
        cfg = _carregar_nfe_config()
    except Exception:
        cfg = _nfe_config_defaults()

    modo = _as_str(cfg.get("modo_ativo")).lower()
    consulta_url = _as_str(cfg.get("consulta_url")) or _nfe_consulta_url_default()
    destinatario_cnpj = _as_str(cfg.get("destinatario_cnpj"))
    uf_autor = _nfe_normalizar_uf_autor(cfg.get("uf_autor"))
    certificado_arquivo = _as_str(cfg.get("certificado_arquivo"))
    certificado_existe = bool(certificado_arquivo and os.path.exists(certificado_arquivo))
    senha_configurada = bool(_as_str(cfg.get("certificado_senha")))
    deps_faltando = []
    if getattr(nfe_ws, "requests", None) is None:
        deps_faltando.append("requests")
    if getattr(nfe_ws, "pkcs12", None) is None:
        deps_faltando.append("cryptography")
    if getattr(nfe_ws, "etree", None) is None:
        deps_faltando.append("lxml")
    if getattr(nfe_ws, "XMLSigner", None) is None or getattr(nfe_ws, "methods", None) is None:
        deps_faltando.append("signxml")

    pendencias = []
    if not bool(cfg.get("habilitado")):
        pendencias.append("Ativar integracao NF-e.")

    if modo == "portal_assistido":
        if not consulta_url:
            pendencias.append("Preencher a URL oficial da consulta publica.")
        configurado = bool(consulta_url)
        pronto_portal = bool(cfg.get("habilitado")) and configurado
        pronto_dfe = False
    else:
        if not destinatario_cnpj or len(re.sub(r"\D+", "", destinatario_cnpj)) != 14:
            pendencias.append("Preencher o CNPJ do destinatario com 14 digitos.")
        if not uf_autor:
            pendencias.append("Preencher a UF autora do destinatario.")
        if not certificado_arquivo:
            pendencias.append("Informar o caminho do certificado digital.")
        elif not certificado_existe:
            pendencias.append("Garantir que o arquivo do certificado exista no servidor/container.")
        if not senha_configurada:
            pendencias.append("Preencher a senha do certificado digital.")
        if deps_faltando:
            pendencias.append("Instalar dependencias Python do DF-e: " + ", ".join(deps_faltando) + ".")
        configurado = bool(destinatario_cnpj and uf_autor and certificado_arquivo and senha_configurada)
        pronto_portal = False
        pronto_dfe = bool(cfg.get("habilitado")) and configurado and certificado_existe and not deps_faltando

    if not bool(cfg.get("habilitado")):
        resumo_status = "Integracao NF-e desativada."
    elif modo == "portal_assistido":
        resumo_status = "Portal assistido pronto para abrir a consulta publica." if pronto_portal else "Portal assistido com pendencias de configuracao."
    else:
        resumo_status = "DF-e pronto para consultar chave, sincronizar NSU e manifestar ciencia." if pronto_dfe else "DF-e com pendencias de configuracao."

    limite_consultas = _nfe_dfe_limite_status(cfg)

    return {
        "habilitado": bool(cfg.get("habilitado")),
        "modo_ativo": modo,
        "modo_label": _nfe_mode_label(modo),
        "ambiente": _nfe_normalizar_ambiente(cfg.get("ambiente")),
        "consulta_url": consulta_url,
        "abrir_portal_ao_bipar": bool(cfg.get("abrir_portal_ao_bipar")),
        "bloquear_notas_duplicadas": bool(cfg.get("bloquear_notas_duplicadas")),
        "destinatario_cnpj": destinatario_cnpj,
        "uf_autor": uf_autor,
        "cuf_autor": _nfe_cuf_autor(uf_autor),
        "certificado_arquivo": certificado_arquivo,
        "certificado_existe": certificado_existe,
        "senha_configurada": senha_configurada,
        "ultimo_nsu": re.sub(r"\D+", "", _as_str(cfg.get("ultimo_nsu"))),
        "auto_manifestar_ciencia": bool(cfg.get("auto_manifestar_ciencia")),
        "dependencias_dfe_faltando": deps_faltando,
        "pronto_portal": pronto_portal,
        "pronto_dfe": pronto_dfe,
        "limite_consultas_dfe": limite_consultas,
        "pendencias": pendencias,
        "resumo_status": resumo_status,
        "configurado": configurado,
        "updated_at": _fmt_dt(cfg.get("updated_at")),
    }

def _nfe_config_df_e():
    cfg = _carregar_nfe_config()
    if not _as_bool(cfg.get("habilitado"), False):
        raise RuntimeError("A integracao NF-e esta desativada na configuracao.")
    if _as_str(cfg.get("modo_ativo")).lower() != "certificado_digital":
        raise RuntimeError("Ative o modo 'Certificado digital / DF-e' para usar a distribuicao oficial.")

    cnpj = re.sub(r"\D+", "", _as_str(cfg.get("destinatario_cnpj")))
    if len(cnpj) != 14:
        raise RuntimeError("Informe o CNPJ do destinatario com 14 digitos na configuracao NF-e.")

    uf_autor = _nfe_normalizar_uf_autor(cfg.get("uf_autor"))
    if not uf_autor:
        raise RuntimeError("Informe a UF autora da empresa na configuracao NF-e.")

    certificado_arquivo = _as_str(cfg.get("certificado_arquivo"))
    if not certificado_arquivo:
        raise RuntimeError("Informe o caminho do certificado digital (.pfx/.p12) na configuracao NF-e.")
    if not os.path.exists(certificado_arquivo):
        raise RuntimeError("O arquivo de certificado digital configurado nao foi encontrado no servidor.")

    return {
        **cfg,
        "ambiente": _nfe_normalizar_ambiente(cfg.get("ambiente")),
        "destinatario_cnpj": cnpj,
        "uf_autor": uf_autor,
        "cuf_autor": _nfe_cuf_autor(uf_autor),
        "certificado_arquivo": certificado_arquivo,
        "certificado_senha": _as_str(cfg.get("certificado_senha")),
        "ultimo_nsu": re.sub(r"\D+", "", _as_str(cfg.get("ultimo_nsu"))),
        "auto_manifestar_ciencia": _as_bool(cfg.get("auto_manifestar_ciencia"), True),
    }

def _persistir_nfe_config_campos(**updates):
    if not updates:
        return _carregar_nfe_config()

    cfg_atual = _carregar_nfe_config()
    payload = {**cfg_atual}
    payload.update(updates)
    return _persistir_nfe_config(payload)

def _nfe_resumo_distribuicao_publico(resultado):
    consulta = resultado.get("consulta") if isinstance(resultado, dict) else {}
    manifestacao = resultado.get("manifestacao") if isinstance(resultado, dict) else {}
    documento = resultado.get("documento") if isinstance(resultado, dict) else {}
    if not isinstance(consulta, dict):
        consulta = {}
    if not isinstance(manifestacao, dict):
        manifestacao = {}
    if not isinstance(documento, dict):
        documento = {}
    docs = consulta.get("documentos") if isinstance(consulta, dict) else []
    return {
        "c_stat": _as_str(consulta.get("c_stat")),
        "x_motivo": _as_str(consulta.get("x_motivo")),
        "ult_nsu": _as_str(consulta.get("ult_nsu")),
        "max_nsu": _as_str(consulta.get("max_nsu")),
        "documentos_encontrados": len(docs) if isinstance(docs, list) else 0,
        "schema_documento": _as_str(documento.get("schema")),
        "root_type": _as_str(documento.get("root_type")),
        "manifestacao_c_stat": _as_str(manifestacao.get("c_stat")),
        "manifestacao_x_motivo": _as_str(manifestacao.get("x_motivo")),
        "manifestado": bool(resultado.get("manifestado")) if isinstance(resultado, dict) else False,
    }


def _nfe_resumo_chave_acesso(chave_acesso):
    chave = _normalizar_chave_acesso_nfe(chave_acesso)
    if len(chave) != 44:
        return {
            "chave_acesso": "",
            "emitente_cnpj": "",
            "modelo": "",
            "serie": "",
            "numero_nota": "",
        }
    return {
        "chave_acesso": chave,
        "emitente_cnpj": chave[6:20],
        "modelo": chave[20:22],
        "serie": str(int(chave[22:25] or "0")) if chave[22:25].isdigit() else chave[22:25],
        "numero_nota": str(int(chave[25:34] or "0")) if chave[25:34].isdigit() else chave[25:34],
    }


def _nfe_resumo_documento(resultado, chave_acesso=""):
    resultado = resultado if isinstance(resultado, dict) else {}
    chave_base = _normalizar_chave_acesso_nfe(chave_acesso)
    consulta = resultado.get("consulta") if isinstance(resultado.get("consulta"), dict) else {}
    documento = resultado.get("documento") if isinstance(resultado.get("documento"), dict) else {}
    documentos = consulta.get("documentos") if isinstance(consulta.get("documentos"), list) else []
    candidatos = []
    if documento:
        candidatos.append(documento)
    candidatos.extend(doc for doc in documentos if isinstance(doc, dict))

    resumo_doc = None
    for doc in candidatos:
        root_type = _as_str(doc.get("root_type"))
        schema = _as_str(doc.get("schema")).lower()
        xml_text = _as_str(doc.get("xml_text"))
        if not xml_text:
            continue
        if root_type == "resNFe" or "resnfe" in schema:
            resumo_doc = doc
            break
        if not resumo_doc:
            resumo_doc = doc

    if not resumo_doc:
        return {}

    xml_text = _as_str(resumo_doc.get("xml_text"))
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return {}

    root_name = _xml_local_name(root.tag)
    resumo = root if root_name == "resNFe" else _xml_child(root, "resNFe")
    if resumo is None:
        return {}

    chave_resumo = _normalizar_chave_acesso_nfe(
        _xml_text(resumo, "chNFe")
        or resumo_doc.get("chave_acesso")
        or chave_base
    )
    chave_meta = _nfe_resumo_chave_acesso(chave_resumo or chave_base)
    detalhe = _nfe_resumo_distribuicao_publico(resultado)
    aviso = (
        "Documento localizado, mas a SEFAZ nao liberou o XML completo. "
        "Os itens nao vieram nesta consulta."
    )

    return _normalizar_preview_nfe({
        "source_type": "dfe",
        "preview_tipo": "parcial",
        "limitation_message": aviso,
        "arquivo_origem": "NFeDistribuicaoDFe",
        "numero_nota": _xml_text(resumo, "nNF") or chave_meta.get("numero_nota"),
        "serie": _xml_text(resumo, "serie") or chave_meta.get("serie"),
        "chave_acesso": chave_resumo or chave_meta.get("chave_acesso"),
        "data_emissao": _xml_text(resumo, "dhEmi") or _xml_text(resumo, "dEmi"),
        "emitente_nome": _xml_text(resumo, "xNome"),
        "emitente_cnpj": _xml_text(resumo, "CNPJ") or _xml_text(resumo, "CPF") or chave_meta.get("emitente_cnpj"),
        "valor_total": _xml_text(resumo, "vNF"),
        "itens": [],
        "warnings": [
            aviso,
            (
                "Use o XML oficial, PDF de contingencia ou inclua os itens manualmente "
                "se precisar concluir esta conferencia."
            ),
            (
                "Retorno DF-e: "
                + (
                    detalhe.get("manifestacao_x_motivo")
                    or detalhe.get("x_motivo")
                    or "resumo localizado sem XML completo"
                )
            ),
        ],
    })


def _nfe_xml_cache_path(chave_acesso):
    chave = _normalizar_chave_acesso_nfe(chave_acesso)
    if len(chave) != 44:
        return ""
    return os.path.join(NFE_XML_CACHE_DIR, f"{chave}.xml")


def _salvar_xml_nfe_cache(chave_acesso, xml_text):
    chave = _normalizar_chave_acesso_nfe(chave_acesso)
    xml_text = _as_str(xml_text)
    if len(chave) != 44 or not xml_text:
        return ""
    cache_path = _nfe_xml_cache_path(chave)
    if not cache_path:
        return ""
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(xml_text)
    except Exception:
        return ""
    return cache_path


def _carregar_xml_nfe_cache(chave_acesso):
    cache_path = _nfe_xml_cache_path(chave_acesso)
    if not cache_path or not os.path.exists(cache_path):
        return ""
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _remover_xml_nfe_cache(chave_acesso):
    cache_path = _nfe_xml_cache_path(chave_acesso)
    if not cache_path or not os.path.exists(cache_path):
        return False
    try:
        os.remove(cache_path)
        return True
    except Exception:
        return False


def _nfe_dfe_limite_key(cfg):
    ambiente = _nfe_normalizar_ambiente((cfg or {}).get("ambiente"))
    cnpj = _normalizar_chave_acesso_nfe((cfg or {}).get("destinatario_cnpj"))
    return f"{ambiente}:{cnpj or 'sem_cnpj'}"


def _nfe_dfe_limite_load():
    if not os.path.exists(NFE_DFE_LIMIT_FILE):
        return {}
    try:
        with open(NFE_DFE_LIMIT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _nfe_dfe_limite_save(data):
    try:
        with open(NFE_DFE_LIMIT_FILE, "w", encoding="utf-8") as f:
            json.dump(data or {}, f, ensure_ascii=False)
    except Exception:
        pass


def _nfe_dfe_limite_registrar(cfg=None, bloquear_por_segundos=0):
    cfg = cfg or _carregar_nfe_config()
    limite = 20
    janela_segundos = 3600
    agora = int(time.time())
    key = _nfe_dfe_limite_key(cfg)

    with _nfe_dfe_limit_lock:
        data = _nfe_dfe_limite_load()
        registro = data.get(key)
        if not isinstance(registro, dict):
            registro = {}
        timestamps = registro.get("timestamps")
        if not isinstance(timestamps, list):
            timestamps = []
        timestamps = [int(ts) for ts in timestamps if isinstance(ts, (int, float)) and int(ts) > (agora - janela_segundos)]
        if bloquear_por_segundos > 0:
            registro["blocked_until"] = agora + int(bloquear_por_segundos)
        else:
            timestamps.append(agora)
        registro["timestamps"] = timestamps
        data[key] = registro
        _nfe_dfe_limite_save(data)

    return _nfe_dfe_limite_status(cfg)


def _nfe_dfe_limite_status(cfg=None):
    cfg = cfg or _carregar_nfe_config()
    limite = 20
    janela_segundos = 3600
    agora = int(time.time())
    key = _nfe_dfe_limite_key(cfg)

    with _nfe_dfe_limit_lock:
        data = _nfe_dfe_limite_load()
        registro = data.get(key)
        if not isinstance(registro, dict):
            registro = {}
        timestamps = registro.get("timestamps")
        if not isinstance(timestamps, list):
            timestamps = []
        timestamps = [int(ts) for ts in timestamps if isinstance(ts, (int, float)) and int(ts) > (agora - janela_segundos)]
        blocked_until = _as_int(registro.get("blocked_until"), 0)
        if blocked_until <= agora:
            blocked_until = 0
        registro["timestamps"] = timestamps
        registro["blocked_until"] = blocked_until
        data[key] = registro
        _nfe_dfe_limite_save(data)

    mais_antiga = timestamps[0] if timestamps else 0
    bloqueado_por_janela = len(timestamps) >= limite
    aguardar_janela = max((mais_antiga + janela_segundos) - agora, 0) if bloqueado_por_janela and mais_antiga else 0
    aguardar_bloqueio = max(blocked_until - agora, 0) if blocked_until else 0
    bloqueado = bloqueado_por_janela or blocked_until > 0
    return {
        "limite": limite,
        "usadas": len(timestamps),
        "restantes": max(limite - len(timestamps), 0),
        "janela_segundos": janela_segundos,
        "bloqueado": bloqueado,
        "aguardar_segundos": max(aguardar_janela, aguardar_bloqueio),
        "blocked_until": blocked_until,
        "ambiente": _nfe_normalizar_ambiente(cfg.get("ambiente")),
        "chave_cache_local": key,
    }

def _preview_nfe_estoque_from_xml_text(xml_text, arquivo_origem="", chave_acesso_esperada=""):
    if not _as_str(xml_text):
        raise ValueError("envie um XML valido da NF-e")

    nfe = _parse_nfe_xml_text(xml_text)
    preview = _normalizar_preview_nfe({
        **nfe,
        "source_type": "xml",
        "arquivo_origem": _as_str(arquivo_origem),
        "warnings": [],
    })
    chave_preview = _normalizar_chave_acesso_nfe(preview.get("chave_acesso"))
    chave_acesso_esperada = _normalizar_chave_acesso_nfe(chave_acesso_esperada)
    if chave_acesso_esperada:
        if chave_preview and chave_preview != chave_acesso_esperada:
            raise ValueError("a chave bipada nao confere com o XML retornado pela NF-e")
        if not chave_preview:
            preview["chave_acesso"] = chave_acesso_esperada
            preview["warnings"] = (preview.get("warnings") or []) + [
                "A chave informada foi aplicada ao rascunho porque o XML nao trouxe a chave automaticamente."
            ]
    chave_cache = _normalizar_chave_acesso_nfe(preview.get("chave_acesso")) or chave_acesso_esperada
    if chave_cache:
        _salvar_xml_nfe_cache(chave_cache, xml_text)
    return _normalizar_preview_nfe(preview)

def _preview_nfe_estoque_por_dfe(chave_acesso, arquivo_origem="NFeDistribuicaoDFe", warnings=None, manifestar_automaticamente=None):
    resultado = _buscar_xml_nfe_por_chave_df_e(
        chave_acesso,
        manifestar_automaticamente=manifestar_automaticamente,
    )
    xml_text = _as_str(resultado.get("xml_text"))
    if xml_text:
        preview = _preview_nfe_estoque_from_xml_text(
            xml_text,
            arquivo_origem=arquivo_origem,
            chave_acesso_esperada=chave_acesso,
        )
        preview["source_type"] = "dfe"
        preview["preview_tipo"] = "completo"
        preview["arquivo_origem"] = _as_str(arquivo_origem) or "NFeDistribuicaoDFe"
    else:
        preview = _nfe_resumo_documento(resultado, chave_acesso=chave_acesso)
        if not preview:
            raise ValueError("Nao foi possivel montar um resumo da NF-e localizada no DF-e.")
        preview["source_type"] = "dfe"
        preview["preview_tipo"] = "parcial"
        preview["arquivo_origem"] = _as_str(arquivo_origem) or "NFeDistribuicaoDFe"
    extras = [_as_str(item) for item in (warnings or []) if _as_str(item)]
    if bool(resultado.get("cache_local")):
        extras.append("XML carregado do cache local salvo anteriormente para esta chave.")
    if extras:
        preview["warnings"] = extras + (preview.get("warnings") or [])
    return _normalizar_preview_nfe(preview), resultado

def _buscar_xml_nfe_por_chave_df_e(chave_acesso, manifestar_automaticamente=None):
    cfg = _nfe_config_df_e()
    chave_acesso = _normalizar_chave_acesso_nfe(chave_acesso)
    if manifestar_automaticamente is None:
        manifestar_automaticamente = cfg.get("auto_manifestar_ciencia")

    limite_consultas = _nfe_dfe_limite_status(cfg)

    xml_cache = _carregar_xml_nfe_cache(chave_acesso)
    if xml_cache:
        return {
            "consulta": {
                "c_stat": "CACHE",
                "x_motivo": "XML carregado do cache local",
                "documentos": [],
            },
            "manifestacao": None,
            "documento": {
                "schema": "cache_local.xml",
                "root_type": "nfeProc",
                "chave_acesso": chave_acesso,
                "xml_text": xml_cache,
            },
            "xml_text": xml_cache,
            "manifestado": False,
            "cache_local": True,
            "limite_consultas": limite_consultas,
        }

    if limite_consultas.get("bloqueado"):
        aguardar = _as_int(limite_consultas.get("aguardar_segundos"), 0)
        minutos = max(int((aguardar + 59) / 60), 1) if aguardar > 0 else 60
        raise ValueError(
            f"Limite local de consultas DF-e atingido ({_as_int(limite_consultas.get('usadas'), 0)}/"
            f"{_as_int(limite_consultas.get('limite'), 20)} na ultima hora). "
            f"Aguarde cerca de {minutos} minuto(s) ou reutilize um XML ja salvo no cache local."
        )

    try:
        resultado = nfe_ws.buscar_nfe_por_chave(
            chave_acesso=chave_acesso,
            cnpj=cfg.get("destinatario_cnpj"),
            certificado_arquivo=cfg.get("certificado_arquivo"),
            certificado_senha=cfg.get("certificado_senha"),
            ambiente=cfg.get("ambiente"),
            cuf_autor=cfg.get("cuf_autor"),
            manifestar_automaticamente=_as_bool(manifestar_automaticamente, True),
            timeout=30,
            tentativas_manifestacao=3,
            espera_manifestacao_segundos=3,
        )
    except RuntimeError as exc:
        mensagem = str(exc)
        if "Consumo Indevido" in mensagem or "consumo indevido" in mensagem.lower():
            _nfe_dfe_limite_registrar(cfg, bloquear_por_segundos=3600)
            raise ValueError(
                "Rejeicao por consumo indevido na SEFAZ. O sistema marcou um bloqueio local de 1 hora para esta empresa/ambiente. "
                "Aguarde o periodo ou reutilize um XML ja salvo no cache local."
            ) from exc
        if (
            _nfe_normalizar_ambiente(cfg.get("ambiente")) == "homologacao"
            and "404" in mensagem
            and "NFeDistribuicaoDFe" in mensagem
        ):
            raise ValueError(
                "Ambiente homologacao ativo: a SEFAZ nao localizou essa chave nesse ambiente. "
                "Use apenas notas/chaves de teste em homologacao ou troque o ambiente para producao para consultar notas reais."
            ) from exc
        _nfe_dfe_limite_registrar(cfg)
        raise ValueError(mensagem) from exc

    xml_text = _as_str(resultado.get("xml_text"))
    if not xml_text:
        resumo = _nfe_resumo_distribuicao_publico(resultado)
        detalhe = resumo.get("manifestacao_x_motivo") or resumo.get("x_motivo") or "a SEFAZ ainda nao liberou o XML completo"
        if "Consumo Indevido" in detalhe or "consumo indevido" in detalhe.lower():
            _nfe_dfe_limite_registrar(cfg, bloquear_por_segundos=3600)
            raise ValueError(
                "Rejeicao por consumo indevido na SEFAZ. O sistema marcou um bloqueio local de 1 hora para esta empresa/ambiente. "
                "Aguarde o periodo ou reutilize um XML ja salvo no cache local."
            )
        resultado["resumo_nfe"] = _nfe_resumo_documento(resultado, chave_acesso=chave_acesso)
        resultado["limite_consultas"] = _nfe_dfe_limite_registrar(cfg)
        if resultado.get("resumo_nfe"):
            return resultado
        raise ValueError(f"Nao foi possivel obter o XML completo da NF-e. Detalhe: {detalhe}.")

    _salvar_xml_nfe_cache(chave_acesso, xml_text)
    resultado["limite_consultas"] = _nfe_dfe_limite_registrar(cfg)
    return resultado

def _sincronizar_nfe_dist_nsu(manifestar_automaticamente=None):
    cfg = _nfe_config_df_e()
    if manifestar_automaticamente is None:
        manifestar_automaticamente = cfg.get("auto_manifestar_ciencia")

    try:
        consulta = nfe_ws.consultar_distribuicao(
            cnpj=cfg.get("destinatario_cnpj"),
            certificado_arquivo=cfg.get("certificado_arquivo"),
            certificado_senha=cfg.get("certificado_senha"),
            ambiente=cfg.get("ambiente"),
            cuf_autor=cfg.get("cuf_autor"),
            ult_nsu=cfg.get("ultimo_nsu"),
            timeout=30,
        )
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc

    documentos = []
    manifestacoes = []
    for doc in consulta.get("documentos") or []:
        item = {
            "nsu": _as_str(doc.get("nsu")),
            "schema": _as_str(doc.get("schema")),
            "root_type": _as_str(doc.get("root_type")),
            "chave_acesso": _normalizar_chave_acesso_nfe(doc.get("chave_acesso")),
            "tem_xml": bool(_as_str(doc.get("xml_text"))),
        }
        documentos.append(item)

        if (
            _as_bool(manifestar_automaticamente, True)
            and item["chave_acesso"]
            and item["root_type"] == "resNFe"
        ):
            try:
                evento = nfe_ws.manifestar_nfe(
                    chave_acesso=item["chave_acesso"],
                    cnpj=cfg.get("destinatario_cnpj"),
                    certificado_arquivo=cfg.get("certificado_arquivo"),
                    certificado_senha=cfg.get("certificado_senha"),
                    ambiente=cfg.get("ambiente"),
                    tipo_manifesto="ciencia",
                    timeout=30,
                )
                manifestacoes.append({
                    "chave_acesso": item["chave_acesso"],
                    "c_stat": _as_str(evento.get("c_stat")),
                    "x_motivo": _as_str(evento.get("x_motivo")),
                })
            except Exception as exc:
                manifestacoes.append({
                    "chave_acesso": item["chave_acesso"],
                    "erro": str(exc),
                })

    ultimo_nsu = _as_str(consulta.get("ult_nsu"))
    if ultimo_nsu:
        _persistir_nfe_config_campos(ultimo_nsu=ultimo_nsu)

    return {
        "consulta": consulta,
        "documentos": documentos,
        "manifestacoes": manifestacoes,
        "ultimo_nsu": ultimo_nsu,
        "max_nsu": _as_str(consulta.get("max_nsu")),
        "c_stat": _as_str(consulta.get("c_stat")),
        "x_motivo": _as_str(consulta.get("x_motivo")),
    }

def _validar_nota_duplicada_abastecimento(cur, numero_nota="", chave_acesso_nfe="", exclude_id=0):
    cfg = _carregar_nfe_config()
    if not _as_bool(cfg.get("bloquear_notas_duplicadas"), True):
        return

    nota = _as_str(numero_nota)
    chave = _normalizar_chave_acesso_nfe(chave_acesso_nfe)
    filtros = []
    params = []
    if chave:
        filtros.append("chave_acesso_nfe=%s")
        params.append(chave)
    if nota:
        filtros.append("numero_nota=%s")
        params.append(nota)
    if not filtros:
        return

    sql = f"""
        SELECT id, numero_nota, chave_acesso_nfe, posto, emitente_nome
        FROM abastecimentos
        WHERE ({' OR '.join(filtros)})
    """
    if _as_int(exclude_id, 0) > 0:
        sql += " AND id<>%s"
        params.append(_as_int(exclude_id, 0))
    sql += " ORDER BY id DESC LIMIT 1"
    cur.execute(sql, tuple(params))
    row = cur.fetchone()
    if row:
        if isinstance(row, dict):
            row_id = row.get("id")
            row_numero = row.get("numero_nota")
            row_chave = row.get("chave_acesso_nfe")
        else:
            row_id = row[0] if len(row) > 0 else 0
            row_numero = row[1] if len(row) > 1 else ""
            row_chave = row[2] if len(row) > 2 else ""
        raise ValueError(
            f"nota ja cadastrada no abastecimento #{_as_int(row_id, 0)} "
            f"({(_as_str(row_numero) or _normalizar_chave_acesso_nfe(row_chave) or 'sem nota')})"
        )

def _validar_nota_duplicada_estoque(cur, numero_nota="", chave_acesso_nfe="", emitente_nome="", exclude_conferencia_id=0):
    cfg = _carregar_nfe_config(cur)
    if not _as_bool(cfg.get("bloquear_notas_duplicadas"), True):
        return

    nota = _as_str(numero_nota)
    chave = _normalizar_chave_acesso_nfe(chave_acesso_nfe)
    emitente = _as_str(emitente_nome)

    if chave:
        sql = """
            SELECT id, numero_nota, chave_acesso, emitente_nome, status
            FROM estoque_conferencias
            WHERE chave_acesso=%s
        """
        params = [chave]
        if _as_int(exclude_conferencia_id, 0) > 0:
            sql += " AND id<>%s"
            params.append(_as_int(exclude_conferencia_id, 0))
        sql += " ORDER BY id DESC LIMIT 1"
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        if row:
            raise ValueError(
                f"esta NF-e ja foi registrada no estoque pela conferencia #{_as_int(row.get('id'), 0)} "
                f"(status: {_as_str(row.get('status')) or 'pendente'})"
            )

    if nota:
        sql = """
            SELECT id, numero_nota, chave_acesso, emitente_nome, status
            FROM estoque_conferencias
            WHERE numero_nota=%s
        """
        params = [nota]
        if emitente:
            sql += " AND emitente_nome=%s"
            params.append(emitente)
        if _as_int(exclude_conferencia_id, 0) > 0:
            sql += " AND id<>%s"
            params.append(_as_int(exclude_conferencia_id, 0))
        sql += " ORDER BY id DESC LIMIT 1"
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        if row:
            emitente_label = _as_str(row.get("emitente_nome"))
            detalhe_emitente = f" de {emitente_label}" if emitente_label else ""
            raise ValueError(
                f"a nota {nota}{detalhe_emitente} ja foi registrada no estoque pela conferencia #{_as_int(row.get('id'), 0)} "
                f"(status: {_as_str(row.get('status')) or 'pendente'})"
            )

def _sip_endpoint_ativo():
    cfg = _carregar_sip_config()
    modo_ativo = _as_str(cfg.get("modo_ativo")).lower() or "freepbx"
    profile = cfg.get(modo_ativo) or {}
    ws_url = _as_str(profile.get("ws_url"))
    if not ws_url:
        raise RuntimeError("WebSocket SIP nao configurado.")

    parsed = urlparse(ws_url)
    scheme = _as_str(parsed.scheme).lower()
    host = _as_str(parsed.hostname)
    if not host or scheme not in ("ws", "wss"):
        raise RuntimeError("WS URL SIP invalida.")

    port = parsed.port or (443 if scheme == "wss" else 80)
    if port <= 0:
        raise RuntimeError("Porta do endpoint SIP invalida.")

    return {
        "modo": modo_ativo,
        "profile": profile,
        "ws_url": ws_url,
        "scheme": scheme,
        "host": host,
        "port": port,
        "path": parsed.path or "/",
    }

def _sha1_thumbprint(cert_der):
    sha1 = hashlib.sha1(cert_der).hexdigest().upper()
    return ":".join(sha1[i:i+2] for i in range(0, len(sha1), 2))

def _primeiro_cert_pem(pem_text):
    begin = "-----BEGIN CERTIFICATE-----"
    end = "-----END CERTIFICATE-----"
    start = pem_text.find(begin)
    finish = pem_text.find(end)
    if start < 0 or finish < 0:
        raise RuntimeError("Arquivo de certificado invalido.")
    finish += len(end)
    cert = pem_text[start:finish]
    return cert if cert.endswith("\n") else f"{cert}\n"

def _carregar_certificado_local(path):
    if not os.path.exists(path):
        raise RuntimeError(f"Certificado nao encontrado: {path}")
    with open(path, "r", encoding="utf-8") as f:
        pem_all = f.read()
    pem = _primeiro_cert_pem(pem_all)
    cert_der = ssl.PEM_cert_to_DER_cert(pem)
    return {
        "pem": pem,
        "sha1": _sha1_thumbprint(cert_der),
        "der_b64": base64.b64encode(cert_der).decode("ascii"),
    }

def _app_https_cert_path():
    return os.path.join(BASE_DIR, "certs", "fullchain.pem")

def _baixar_certificado_tls(host, port, timeout=8):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls_sock:
            cert_der = tls_sock.getpeercert(binary_form=True)
    if not cert_der:
        raise RuntimeError("O servidor nao retornou certificado TLS.")
    cert_pem = ssl.DER_cert_to_PEM_cert(cert_der)
    return {
        "pem": cert_pem,
        "sha1": _sha1_thumbprint(cert_der),
        "der_b64": base64.b64encode(cert_der).decode("ascii"),
    }

def _pkcs12_export_password():
    return _as_str(_env("RB_CERT_EXPORT_PASSWORD", "riob1951")) or "riob1951"

def _cert_der_bytes(cert_info):
    return base64.b64decode(cert_info["der_b64"])

def _ca_cert_path():
    return os.path.join(BASE_DIR, "certs", "riobranco-ca.crt")

def _carregar_ca_local(required=False):
    path = _ca_cert_path()
    if os.path.exists(path):
        return _carregar_certificado_local(path)
    if required:
        raise RuntimeError(f"Certificado CA nao encontrado: {path}")
    return None

def _certificados_confianca_cliente():
    ca_cert = _carregar_ca_local(False)
    if ca_cert:
        return [{
            "label": "CA interna RioBranco",
            "cert": ca_cert,
            "is_ca": True,
            "pem_filename": "riobranco-ca.pem",
            "crt_filename": "riobranco-ca.crt",
            "mobileconfig_name": "RioBranco CA",
            "mobileconfig_desc": "Autoridade certificadora interna do RioBranco",
            "mobileconfig_id": "br.com.riobranco.cert.ca",
        }]

    endpoint = _sip_endpoint_ativo()
    app_cert = _carregar_certificado_local(_app_https_cert_path())
    sip_cert = _baixar_certificado_tls(endpoint["host"], endpoint["port"])
    host = endpoint["host"].replace("/", "_")
    return [
        {
            "label": "HTTPS do sistema",
            "cert": app_cert,
            "is_ca": False,
            "pem_filename": "riobranco-web.pem",
            "crt_filename": "riobranco-web.crt",
            "mobileconfig_name": "RioBranco HTTPS",
            "mobileconfig_desc": "Certificado HTTPS do sistema RioBranco",
            "mobileconfig_id": "br.com.riobranco.cert.web",
        },
        {
            "label": "SIP/WSS do FreePBX",
            "cert": sip_cert,
            "is_ca": False,
            "pem_filename": f"riobranco-sip-{host}.pem",
            "crt_filename": f"riobranco-sip-{host}.crt",
            "mobileconfig_name": "RioBranco SIP/WSS",
            "mobileconfig_desc": "Certificado SIP/WSS do FreePBX RioBranco",
            "mobileconfig_id": "br.com.riobranco.cert.sip",
        },
    ]

def _gerar_bundle_pkcs12(certificados, nome_arquivo, senha, alias="RioBranco Certificados"):
    work_dir = os.path.join("/tmp", f"pkcs12_{uuid.uuid4().hex}")
    os.makedirs(work_dir, exist_ok=True)
    try:
        cert_paths = []
        for idx, cert in enumerate(certificados, start=1):
            cert_path = os.path.join(work_dir, f"cert_{idx}.pem")
            with open(cert_path, "w", encoding="utf-8") as f:
                pem = _primeiro_cert_pem(cert.get("pem", ""))
                f.write(pem)
            cert_paths.append(cert_path)

        bundle_path = os.path.join(work_dir, nome_arquivo)
        comando = [
            "openssl",
            "pkcs12",
            "-export",
            "-nokeys",
            "-out", bundle_path,
            "-in", cert_paths[0],
            "-name", alias,
            "-passout", f"pass:{senha}",
        ]
        for extra_cert in cert_paths[1:]:
            comando.extend(["-certfile", extra_cert])

        p = subprocess.run(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode != 0 or not os.path.exists(bundle_path):
            detalhe = (p.stderr or p.stdout or "").strip()
            raise RuntimeError(detalhe or "Falha ao gerar bundle PKCS#12.")

        with open(bundle_path, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

def _public_base_url():
    explicit = _as_str(_env("RB_PUBLIC_BASE_URL", "")).rstrip("/")
    if explicit:
        return explicit

    https_enabled = _as_bool(_env("RB_ENABLE_HTTPS", "0"), False)
    server_name = _as_str(_env("RB_SERVER_NAME", "")).strip()
    scheme = "https" if https_enabled else "http"
    port = _env_int("RB_HTTPS_PORT", 443 if https_enabled else 80) if https_enabled else _env_int("RB_HTTP_PORT", 80)

    if server_name and server_name != "_":
        default_port = 443 if scheme == "https" else 80
        host = server_name if port == default_port else f"{server_name}:{port}"
        return f"{scheme}://{host}"

    forwarded_proto = _as_str(request.headers.get("X-Forwarded-Proto")).lower()
    forwarded_host = _as_str(request.headers.get("X-Forwarded-Host"))
    host = forwarded_host or _as_str(request.headers.get("Host")) or urlparse(request.host_url).netloc
    scheme = forwarded_proto or ("https" if https_enabled else _as_str(request.scheme).lower() or "http")
    return f"{scheme}://{host}".rstrip("/")

def _bootstrap_sip_config_from_env():
    env_cfg = _sip_config_from_env()
    if _sip_config_is_blank(env_cfg):
        return

    force = _as_bool(_env("RB_SIP_BOOTSTRAP_FORCE", "0"), False)
    try:
        atual = _carregar_sip_config()
    except Exception as exc:
        print("WARN sip bootstrap load:", exc)
        return

    if not force and not _sip_config_is_blank(atual):
        return

    try:
        _persistir_sip_config(
            env_cfg.get("habilitado"),
            env_cfg.get("modo_ativo"),
            env_cfg.get("setevoip_direto"),
            env_cfg.get("freepbx"),
        )
    except Exception as exc:
        print("WARN sip bootstrap persist:", exc)

def _usuario_publico_dict(row):
    return {
        "id": _as_int(row.get("id"), 0),
        "nome": _as_str(row.get("nome")),
        "login": _as_str(row.get("login")),
        "ativo": bool(_as_int(row.get("ativo"), 1)),
        "sip_habilitado": bool(_as_int(row.get("sip_habilitado"), 0)),
        "sip_usuario": _as_str(row.get("sip_usuario")),
        "sip_ramal": _as_str(row.get("sip_ramal")),
        "codbar_modo": _normalizar_codbar_modo(row.get("codbar_modo")),
        "data_cadastro": _fmt_dt(row.get("data_cadastro")),
    }

def _portal_usuario_headers():
    uid = _as_int(request.headers.get("X-Usuario-Id"), 0)
    login = _as_str(request.headers.get("X-Usuario-Login"))
    nome = _as_str(request.headers.get("X-Usuario-Nome")) or login
    if uid <= 0 and not login:
        return None
    if not login:
        login = f"portal-{uid}"
    if not nome:
        nome = login
    return {"id": uid, "nome": nome, "login": login}

def _ensure_portal_usuario(conn):
    portal_user = _portal_usuario_headers()
    if not portal_user:
        return None

    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT id, nome, login, ativo, sip_habilitado, sip_usuario, sip_ramal, codbar_modo, data_cadastro
            FROM usuarios
            WHERE id=%s OR login=%s
            ORDER BY CASE WHEN id=%s THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (portal_user["id"], portal_user["login"], portal_user["id"]),
        )
        row = cur.fetchone()
        if row:
            updates = []
            params = []
            if portal_user["nome"] and _as_str(row.get("nome")) != portal_user["nome"]:
                updates.append("nome=%s")
                params.append(portal_user["nome"])
            if _as_int(row.get("ativo"), 1) != 1:
                updates.append("ativo=1")
            if updates:
                params.append(row["id"])
                cur.execute(f"UPDATE usuarios SET {', '.join(updates)} WHERE id=%s", params)
                conn.commit()
                row["nome"] = portal_user["nome"] or row.get("nome")
                row["ativo"] = 1
            return _usuario_publico_dict(row)

        senha_sistema = generate_password_hash(uuid.uuid4().hex)
        if portal_user["id"] > 0:
            cur.execute(
                """
                INSERT INTO usuarios (id, nome, login, senha, ativo, codbar_modo)
                VALUES (%s, %s, %s, %s, 1, 'bip')
                """,
                (portal_user["id"], portal_user["nome"], portal_user["login"], senha_sistema),
            )
        else:
            cur.execute(
                """
                INSERT INTO usuarios (nome, login, senha, ativo, codbar_modo)
                VALUES (%s, %s, %s, 1, 'bip')
                """,
                (portal_user["nome"], portal_user["login"], senha_sistema),
            )
        conn.commit()
        local_id = portal_user["id"] if portal_user["id"] > 0 else cur.lastrowid
        cur.execute(
            """
            SELECT id, nome, login, ativo, sip_habilitado, sip_usuario, sip_ramal, codbar_modo, data_cadastro
            FROM usuarios
            WHERE id=%s
            LIMIT 1
            """,
            (local_id,),
        )
        return _usuario_publico_dict(cur.fetchone() or {})
    finally:
        cur.close()

def _usuario_sip_dict(row):
    return {
        **_usuario_publico_dict(row),
        "sip_senha": _as_str(row.get("sip_senha")),
    }

ensure_schema()
_bootstrap_sip_config_from_env()

def _normalizar_km_base(km_base, km_atual):
    """
    Normaliza KM base para cálculo de ciclos (manutenção/óleo):
    - sem histórico válido -> usa km_atual (ciclo inicia no KM atual)
    - histórico acima do km_atual -> também usa km_atual (reset de odômetro/base)
    """
    base = _as_int(km_base, 0)
    atual = _as_int(km_atual, 0)
    if base <= 0 or base > atual:
        return atual
    return base

def _safe_remove_devolucao_folder(devolucao_id: int):
    """
    Remove apenas a pasta FotosDevolucoes/devolucao_<id> com segurança.
    - Não remove nada fora de FOTOS_DIR
    - Ignora se não existir
    """
    pasta = os.path.join(FOTOS_DIR, f"devolucao_{devolucao_id}")

    # Normaliza e valida se está dentro do diretório permitido
    pasta_abs = os.path.abspath(pasta)
    root_abs = os.path.abspath(FOTOS_DIR)

    if not pasta_abs.startswith(root_abs + os.sep):
        # Segurança extra: jamais apaga fora do diretório
        return False

    if os.path.isdir(pasta_abs):
        shutil.rmtree(pasta_abs, ignore_errors=True)
        return True

    return False

def _save_devolucao_files(devolucao_id: int, files):
    """
    Salva arquivos em FotosDevolucoes/devolucao_<id>/ e retorna lista de paths relativos.
    """
    if not files:
        return []

    pasta = os.path.join(FOTOS_DIR, f"devolucao_{devolucao_id}")
    os.makedirs(pasta, exist_ok=True)

    salvos = []
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    for i, f in enumerate(files, start=1):
        if not f or not f.filename:
            continue

        nome = secure_filename(f.filename)
        if nome == "":
            continue

        final = f"{ts}_{i}_{nome}"
        caminho_abs = os.path.join(pasta, final)
        f.save(caminho_abs)

        rel = f"devolucao_{devolucao_id}/{final}"
        salvos.append(rel)

    return salvos

def _chat_attachment_abs(rel_path: str):
    rel = _as_str(rel_path).replace("\\", "/").lstrip("/")
    if not rel:
        return ""
    caminho_abs = os.path.abspath(os.path.join(CHAT_ATTACHMENTS_DIR, rel))
    root_abs = os.path.abspath(CHAT_ATTACHMENTS_DIR)
    if caminho_abs == root_abs or not caminho_abs.startswith(root_abs + os.sep):
        return ""
    return caminho_abs

def _chat_attachment_is_image(mime: str, nome: str):
    mime = _as_str(mime).lower()
    if mime.startswith("image/"):
        return True
    guessed = (mimetypes.guess_type(_as_str(nome))[0] or "").lower()
    return guessed.startswith("image/")

def _save_chat_attachment(file_storage):
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None

    nome_original = secure_filename(file_storage.filename or "")
    if not nome_original:
        return None

    pasta_rel = datetime.datetime.now().strftime("%Y%m")
    pasta_abs = os.path.join(CHAT_ATTACHMENTS_DIR, pasta_rel)
    os.makedirs(pasta_abs, exist_ok=True)

    final = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:10]}_{nome_original}"
    caminho_abs = os.path.join(pasta_abs, final)
    file_storage.save(caminho_abs)

    mime = (_as_str(getattr(file_storage, "mimetype", "")) or mimetypes.guess_type(nome_original)[0] or "application/octet-stream")
    try:
        tamanho = int(os.path.getsize(caminho_abs) or 0)
    except Exception:
        tamanho = 0

    return {
        "nome": nome_original,
        "path": f"{pasta_rel}/{final}",
        "mime": mime,
        "tamanho": tamanho,
        "abs_path": caminho_abs,
    }

def _build_abastecimento_pdf(row):
    """Gera PDF da requisição de abastecimento e retorna caminho absoluto."""
    req_id = _as_int(row.get("id"), 0)
    arquivo = os.path.join(REQ_ABAST_DIR, f"requisicao_abastecimento_{req_id}.pdf")
    doc = SimpleDocTemplate(
        arquivo,
        topMargin=24,
        leftMargin=36,
        rightMargin=36,
        bottomMargin=36
    )
    styles = getSampleStyleSheet()
    elementos = []

    data_liberacao = _fmt_dt(row.get("data_liberacao")) or "-"
    veiculo_nome = (row.get("veiculo_nome") or "").strip()
    placa = (row.get("placa") or "").strip()
    modelo = (row.get("modelo") or "").strip()
    veiculo_label = " / ".join([x for x in [veiculo_nome, placa, modelo] if x]) or f"Veículo #{row.get('veiculo_id')}"

    logo_cell = ""
    logo_path = os.path.join(BASE_DIR, "logo.png")
    if os.path.isfile(logo_path):
        try:
            logo_cell = Image(logo_path, width=64, height=64)
        except Exception:
            logo_cell = ""

    dados_empresa = [
        Paragraph("<b>Bebidas Rio Branco</b>", styles["Heading3"]),
        Paragraph("CNPJ: 20.984.401/0001-30", styles["Normal"]),
        Paragraph("Rua João Nelson Arcipretti, 278 - Centro, Astorga - PR, 86730-000", styles["Normal"]),
        Paragraph("Site: refrigeranteriobranco.com.br", styles["Normal"]),
        Paragraph("E-mail: contato@refrigeranteriobranco.com.br", styles["Normal"]),
    ]

    cabecalho = Table([[logo_cell, dados_empresa]], colWidths=[72, 390])
    cabecalho.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
    ]))
    elementos.append(cabecalho)
    elementos.append(Spacer(1, 12))

    elementos.append(Paragraph("Requisição de Abastecimento para o Posto", styles["Heading2"]))
    elementos.append(Spacer(1, 10))
    elementos.append(Paragraph(f"Numero da Requisicao: {req_id}", styles["Normal"]))
    elementos.append(Paragraph(f"Data de Liberação: {data_liberacao}", styles["Normal"]))
    elementos.append(Paragraph(f"Status: {row.get('status') or 'liberado'}", styles["Normal"]))
    elementos.append(Spacer(1, 8))
    elementos.append(Paragraph(f"Veículo: {veiculo_label}", styles["Normal"]))
    elementos.append(Paragraph(f"KM informado: {_as_int(row.get('km'), 0)}", styles["Normal"]))
    elementos.append(Paragraph(f"Posto: {(row.get('posto') or '-').strip()}", styles["Normal"]))
    elementos.append(Paragraph(f"Combustível: {_combustivel_tipo_label(row.get('combustivel_tipo'))}", styles["Normal"]))
    if _as_str(row.get("numero_nota")):
        elementos.append(Paragraph(f"NF-e: {_as_str(row.get('numero_nota'))}", styles["Normal"]))
    if _as_str(row.get("chave_acesso_nfe")):
        elementos.append(Paragraph(f"Chave de acesso: {_as_str(row.get('chave_acesso_nfe'))}", styles["Normal"]))
    if _as_str(row.get("emitente_nome")):
        elementos.append(Paragraph(f"Emitente: {_as_str(row.get('emitente_nome'))}", styles["Normal"]))
    if _as_str(row.get("status")).lower() == "abastecido":
        elementos.append(Paragraph(f"Quantidade: {_as_float(row.get('quantidade_litros'), 0.0):.3f}", styles["Normal"]))
        elementos.append(Paragraph(f"Valor: {_fmt_money_br(row.get('valor'))}", styles["Normal"]))
    elementos.append(Spacer(1, 24))
    elementos.append(Paragraph("Assinatura do responsável (empresa): __________________________", styles["Normal"]))
    elementos.append(Spacer(1, 16))
    elementos.append(Paragraph("Assinatura / carimbo do posto: ________________________________", styles["Normal"]))

    doc.build(elementos)
    return arquivo

def _pdf_escape(value):
    txt = _as_str(value)
    if not txt:
        txt = "-"
    return (
        txt.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )

def _fmt_money_br(value):
    n = _as_float(value, 0.0)
    return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _build_report_header(styles):
    logo_cell = ""
    logo_path = os.path.join(BASE_DIR, "logo.png")
    if os.path.isfile(logo_path):
        try:
            logo_cell = Image(logo_path, width=64, height=64)
        except Exception:
            logo_cell = ""

    dados_empresa = [
        Paragraph("<b>Bebidas Rio Branco</b>", styles["Heading3"]),
        Paragraph("CNPJ: 20.984.401/0001-30", styles["Normal"]),
        Paragraph("Rua João Nelson Arcipretti, 278 - Centro, Astorga - PR, 86730-000", styles["Normal"]),
        Paragraph("Site: refrigeranteriobranco.com.br", styles["Normal"]),
        Paragraph("E-mail: contato@refrigeranteriobranco.com.br", styles["Normal"]),
    ]

    cabecalho = Table([[logo_cell, dados_empresa]], colWidths=[72, 620])
    cabecalho.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
    ]))
    return cabecalho

def _build_frota_report_pdf(titulo, headers, rows, slug, filtros=None):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo = os.path.join("/tmp", f"frota_{slug}_{stamp}.pdf")
    doc = SimpleDocTemplate(
        arquivo,
        pagesize=landscape(A4),
        topMargin=24,
        leftMargin=24,
        rightMargin=24,
        bottomMargin=24
    )
    styles = getSampleStyleSheet()
    body_style = styles["BodyText"]
    body_style.fontSize = 8
    body_style.leading = 10

    elementos = [
        _build_report_header(styles),
        Spacer(1, 12),
        Paragraph(titulo, styles["Heading2"]),
        Paragraph(
            f"Gerado em {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            styles["Normal"]
        ),
    ]
    if filtros:
        elementos.append(Paragraph(_pdf_escape("Filtros: " + " | ".join(filtros)), styles["Normal"]))
    elementos.append(Spacer(1, 10))

    table_rows = [[Paragraph(f"<b>{_pdf_escape(h)}</b>", body_style) for h in headers]]
    if rows:
        for row in rows:
            table_rows.append([Paragraph(_pdf_escape(cell), body_style) for cell in row])
    else:
        linha = [Paragraph("Sem registros para o período.", body_style)]
        linha.extend([Paragraph("", body_style) for _ in headers[1:]])
        table_rows.append(linha)

    col_width = doc.width / max(len(headers), 1)
    tabela = Table(table_rows, repeatRows=1, colWidths=[col_width] * len(headers))
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f59e0b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fff7ed")]),
    ]))
    elementos.append(tabela)
    doc.build(elementos)
    return arquivo

FRETE_STATUS_RELATORIO = [
    ("chegada", "Chegou C/ Vasilhames"),
    ("descarregado", "Descarregado Aguardando Carga"),
    ("liberado", "Liberado Para Carregar"),
    ("carregando", "Carregando Em Andamento"),
    ("carregado", "Carregado Liberado P Viajem"),
    ("entregando", "Viajando Em Entrega"),
    ("retornando", "Finalizado Retornando"),
    ("paradoVasio", "Parado (vazio)"),
    ("paradoCarregado", "Parado (carregado)"),
]
FRETE_STATUS_RELATORIO_LABELS = {k: v for k, v in FRETE_STATUS_RELATORIO}
FRETE_STATUS_RELATORIO_ORDER_SQL = ",".join([f"'{k}'" for k, _ in FRETE_STATUS_RELATORIO])
RELATORIO_ESCALA_ORDENACAO = {
    "status_data": {
        "label": "Status do kanban + data",
        "sql": f"FIELD(f.status, {FRETE_STATUS_RELATORIO_ORDER_SQL}), COALESCE(f.data_carga, DATE(f.created_at)) ASC, v.nome ASC, f.id ASC",
    },
    "data_asc": {
        "label": "Data mais antiga primeiro",
        "sql": "COALESCE(f.data_carga, DATE(f.created_at)) ASC, v.nome ASC, f.id ASC",
    },
    "data_desc": {
        "label": "Data mais recente primeiro",
        "sql": "COALESCE(f.data_carga, DATE(f.created_at)) DESC, v.nome ASC, f.id DESC",
    },
    "veiculo": {
        "label": "Caminhao",
        "sql": "v.nome ASC, COALESCE(f.data_carga, DATE(f.created_at)) ASC, f.id ASC",
    },
    "motorista": {
        "label": "Motorista",
        "sql": "m.nome ASC, COALESCE(f.data_carga, DATE(f.created_at)) ASC, f.id ASC",
    },
}

def _parse_frete_status_relatorio(values):
    out = []
    seen = set()
    for raw in (values or []):
        for part in str(raw or "").split(","):
            status = _as_str(part)
            if not status or status not in FRETE_STATUS_RELATORIO_LABELS or status in seen:
                continue
            seen.add(status)
            out.append(status)
    return out

def _coletar_filtros_relatorio_fretes_req():
    data_inicio = _as_date(request.args.get("data_inicio"))
    data_fim = _as_date(request.args.get("data_fim"))
    if data_inicio and data_fim and data_inicio > data_fim:
        data_inicio, data_fim = data_fim, data_inicio

    status_list = _parse_frete_status_relatorio(request.args.getlist("status"))
    ordenacao = _as_str(request.args.get("ordenacao")) or "status_data"
    if ordenacao not in RELATORIO_ESCALA_ORDENACAO:
        ordenacao = "status_data"
    resumo = []
    if data_inicio and data_fim:
        resumo.append(f"Periodo: {data_inicio.strftime('%d/%m/%Y')} ate {data_fim.strftime('%d/%m/%Y')}")
    elif data_inicio:
        resumo.append(f"Periodo: a partir de {data_inicio.strftime('%d/%m/%Y')}")
    elif data_fim:
        resumo.append(f"Periodo: ate {data_fim.strftime('%d/%m/%Y')}")
    if status_list:
        resumo.append("Status: " + ", ".join(FRETE_STATUS_RELATORIO_LABELS[s] for s in status_list))

    return {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "status_list": status_list,
        "ordenacao": ordenacao,
        "resumo": resumo,
    }

def _dados_relatorio_escala(cur, filtros=None):
    filtros = filtros or {}
    headers = ["Data carga", "Caminhao", "Numero", "Motorista", "Ajudante", "Cidade", "Peso", "Qtd entregas"]
    where = []
    params = []

    if filtros.get("data_inicio"):
        where.append("COALESCE(f.data_carga, DATE(f.created_at)) >= %s")
        params.append(filtros["data_inicio"])
    if filtros.get("data_fim"):
        where.append("COALESCE(f.data_carga, DATE(f.created_at)) <= %s")
        params.append(filtros["data_fim"])
    status_list = filtros.get("status_list") or []
    if status_list:
        placeholders = ", ".join(["%s"] * len(status_list))
        where.append(f"f.status IN ({placeholders})")
        params.extend(status_list)
    ordenacao = filtros.get("ordenacao") or "status_data"
    ordem_sql = RELATORIO_ESCALA_ORDENACAO.get(ordenacao, RELATORIO_ESCALA_ORDENACAO["status_data"])["sql"]

    sql = """
        SELECT
            COALESCE(f.data_carga, DATE(f.created_at)) AS data_carga,
            f.peso,
            f.qtd_entregas,
            f.status,
            f.id,
            v.nome AS veiculo_nome,
            v.placa AS veiculo_placa,
            m.nome AS motorista_nome,
            e.nome AS entregador_nome,
            c.nome AS carga_nome
        FROM fretes f
        LEFT JOIN veiculos v ON v.id = f.veiculo_id
        LEFT JOIN motoristas m ON m.id = f.motorista_id
        LEFT JOIN motoristas e ON e.id = f.entregador_id
        LEFT JOIN cargas c ON c.id = f.carga_id
    """
    if where:
        sql += "\nWHERE " + " AND ".join(where)
    sql += f"""
        ORDER BY
            {ordem_sql}
    """
    cur.execute(sql, params)
    rows = [[
        _fmt_date(r.get("data_carga")) or "-",
        r.get("veiculo_nome") or "-",
        r.get("veiculo_placa") or "-",
        r.get("motorista_nome") or "-",
        r.get("entregador_nome") or "-",
        r.get("carga_nome") or "-",
        _frete_hist_num(r.get("peso")),
        str(_as_int(r.get("qtd_entregas"), 0)),
    ] for r in (cur.fetchall() or [])]
    return headers, rows

# =========================================================
# (3) ROTAS: GENÉRICAS / RELATÓRIO / STATUS / BACKUP
# =========================================================
@app.route("/api/relatorio")
def relatorio():
    _limpar_fretes_finalizados_expirados()
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    filtros_frete = _coletar_filtros_relatorio_fretes_req()
    headers, rows = _dados_relatorio_escala(cursor, filtros_frete)
    cursor.close()
    conn.close()

    filtros_pdf = list(filtros_frete.get("resumo") or [])
    filtros_pdf.append("Ordenacao: " + RELATORIO_ESCALA_ORDENACAO[filtros_frete.get("ordenacao") or "status_data"]["label"])
    arquivo = _build_frota_report_pdf("Relatorio de Escala", headers, rows, "escala", filtros_pdf)
    return send_file(arquivo, as_attachment=True, download_name="escala.pdf", mimetype="application/pdf")

@app.route("/api/status")
def status():
    esxi_host = _env("ESXI_HOST", "192.168.200.198")
    esxi_port = _env_int("ESXI_SSH_PORT", 22)
    usuario_logado = None

    def _probe_tcp(host, port, timeout=2.0):
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except Exception:
            return False

    def _camera_target(cam):
        mode = _as_str(cam.get("mode")).lower()
        if mode == "rtsp":
            raw = _as_str(cam.get("rtsp"))
            if raw:
                p = urlparse(raw)
                host = p.hostname
                port = p.port or 554
                if host:
                    return host, port, "rtsp"
        if mode == "hls":
            raw = _as_str(cam.get("hls"))
            if raw:
                p = urlparse(raw)
                host = p.hostname
                port = p.port or (443 if p.scheme == "https" else 80)
                if host:
                    return host, port, "hls"
        return None, None, mode or "-"

    cameras_status = []
    try:
        conn = get_conn()
        usuario_logado = _ensure_portal_usuario(conn)
        conn.close()
        db_ok = True
    except:
        db_ok = False

    esxi_ok = _probe_tcp(esxi_host, esxi_port)

    try:
        import urllib.request
        monitor_cfg = _MONITOR_APPS.get("cameras") or {}
        monitor_port = int(monitor_cfg.get("port") or 8889)
        if _ensure_monitor_app("cameras"):
            req = urllib.request.Request(f"http://127.0.0.1:{monitor_port}/api/list", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                cams_data = json.loads(resp.read().decode("utf-8", errors="ignore")) or {}
            cams = cams_data.get("cams") or []
            for cam in cams:
                cam_id = _as_str(cam.get("id"))
                cam_name = _as_str(cam.get("name")) or cam_id or "Camera"
                host, port, source = _camera_target(cam)
                online = _probe_tcp(host, port) if host and port else False
                cameras_status.append({
                    "id": cam_id,
                    "name": cam_name,
                    "mode": _as_str(cam.get("mode")) or "-",
                    "source": source,
                    "host": host or "-",
                    "port": port or "-",
                    "online": bool(online),
                })
    except Exception:
        cameras_status = []

    monitor_apps = _ensure_monitor_apps()
    sip_status = _sip_status_publico()
    nfe_status = _nfe_status_publico()

    return jsonify({
        "api": True,
        "database": db_ok,
        "esxi": {
            "host": esxi_host,
            "port": esxi_port,
            "online": bool(esxi_ok),
        },
        "monitor_apps": monitor_apps,
        "cameras": cameras_status,
        "sip": sip_status,
        "nfe": nfe_status,
        "usuario_logado": usuario_logado,
    })

@app.route("/api/monitor_boot")
def monitor_boot():
    status = _ensure_monitor_apps()
    return jsonify({"ok": True, "apps": status})

@app.route("/api/backup")
def backup():
    data = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_arquivo = f"backup_{data}.sql"
    arquivo_tmp = os.path.join("/tmp", nome_arquivo)
    arquivo_final = os.path.join(DB_BACKUP_DIR, nome_arquivo)

    comando = [
        "mariadb-dump",
        "--skip-ssl",
        "--databases", db_config["database"],
        "--routines", "--events", "--triggers",
        "--single-transaction", "--quick",
        "--add-drop-database", "--add-drop-table",
        "--default-character-set=utf8mb4",
        "-h", db_config["host"],
        "-P", str(db_config.get("port", 3306)),
        "-u", db_config["user"],
        f"-p{db_config['password']}"
    ]

    try:
        os.makedirs(DB_BACKUP_DIR, exist_ok=True)

        with open(arquivo_tmp, "w", encoding="utf-8") as f:
            p = subprocess.run(comando, stdout=f, stderr=subprocess.PIPE, text=True)

        if p.returncode != 0:
            return jsonify({"erro": "mysqldump falhou", "detalhes": (p.stderr or "").strip()}), 500

        shutil.copyfile(arquivo_tmp, arquivo_final)

        resp = send_file(arquivo_final, as_attachment=True, download_name=nome_arquivo)
        resp.headers["X-Backup-File"] = nome_arquivo
        resp.headers["X-Backup-Stored-Path"] = arquivo_final
        return resp

    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        try:
            if os.path.exists(arquivo_tmp):
                os.remove(arquivo_tmp)
        except Exception:
            pass

@app.route("/api/logs_exclusoes", methods=["GET"])
def listar_logs_exclusoes():
    limite = _as_int(request.args.get("limit"), 200)
    limite = max(1, min(limite, 1000))

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT id, usuario, entidade, item_id, descricao, data_evento
        FROM logs_exclusoes
        ORDER BY id DESC
        LIMIT %s
    """, (limite,))
    rows = cur.fetchall() or []
    cur.close()
    conn.close()

    out = []
    for r in rows:
        out.append({
            "id": _as_int(r.get("id"), 0),
            "usuario": _as_str(r.get("usuario")),
            "entidade": _as_str(r.get("entidade")),
            "item_id": _as_int(r.get("item_id"), 0),
            "descricao": _as_str(r.get("descricao")),
            "data_evento": _fmt_dt(r.get("data_evento")),
        })
    return jsonify(out)

@app.route("/api/sip/config", methods=["GET", "PUT"])
def sip_config_api():
    if request.method == "GET":
        return jsonify(_carregar_sip_config())

    data = request.json or {}
    modo_ativo = _as_str(data.get("modo_ativo")).lower()
    if modo_ativo not in ("setevoip_direto", "freepbx"):
        modo_ativo = "freepbx"

    setevoip_cfg = _sip_profile_from_payload(data.get("setevoip_direto") or data.get("setevoip"))
    freepbx_cfg = _sip_profile_from_payload(data.get("freepbx"))
    cfg = _persistir_sip_config(
        _as_bool(data.get("habilitado"), False),
        modo_ativo,
        setevoip_cfg,
        freepbx_cfg,
    )
    return jsonify({"ok": True, "config": cfg})

@app.route("/api/nfe/config", methods=["GET", "PUT"])
def nfe_config_api():
    if request.method == "GET":
        return jsonify(_carregar_nfe_config())

    data = request.json or {}
    cfg = _persistir_nfe_config(data)
    return jsonify({"ok": True, "config": cfg})

@app.route("/api/nfe/df-e/sincronizar", methods=["POST"])
def nfe_dfe_sincronizar_api():
    data = request.get_json(silent=True) or {}
    manifestar_automaticamente = data.get("manifestar_automaticamente")
    try:
        resultado = _sincronizar_nfe_dist_nsu(manifestar_automaticamente=manifestar_automaticamente)
    except (RuntimeError, ValueError) as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Falha ao sincronizar DF-e: {str(exc)}"}), 500

    return jsonify({
        "ok": True,
        **resultado,
        "config": _carregar_nfe_config(),
        "limite_consultas": resultado.get("limite_consultas") or _nfe_dfe_limite_status(),
    })

@app.route("/api/nfe/df-e/consultar_chave", methods=["POST"])
def nfe_dfe_consultar_chave_api():
    data = request.get_json(silent=True) or {}
    chave_acesso = _normalizar_chave_acesso_nfe(data.get("chave_acesso"))
    manifestar_automaticamente = data.get("manifestar_automaticamente")
    if len(chave_acesso) != 44:
        return jsonify({"erro": "a chave de acesso da NF-e precisa ter 44 digitos."}), 400

    try:
        resultado = _buscar_xml_nfe_por_chave_df_e(
            chave_acesso,
            manifestar_automaticamente=manifestar_automaticamente,
        )
        if _as_str(resultado.get("xml_text")):
            nfe = _normalizar_preview_nfe({
                **_parse_nfe_xml_text(resultado.get("xml_text")),
                "source_type": "dfe",
                "preview_tipo": "completo",
                "arquivo_origem": "NFeDistribuicaoDFe",
                "warnings": [],
            })
        else:
            nfe = _nfe_resumo_documento(resultado, chave_acesso=chave_acesso)
            if not nfe:
                raise ValueError("Nao foi possivel montar o resumo da NF-e localizada.")
    except (RuntimeError, ValueError) as exc:
        return jsonify({"erro": str(exc), "limite_consultas": _nfe_dfe_limite_status()}), 400
    except Exception as exc:
        return jsonify({"erro": f"Falha ao consultar DF-e: {str(exc)}"}), 500

    return jsonify({
        "ok": True,
        "chave_acesso": chave_acesso,
        "nfe": nfe,
        "dfe": _nfe_resumo_distribuicao_publico(resultado),
        "limite_consultas": resultado.get("limite_consultas") or _nfe_dfe_limite_status(),
    })

@app.route("/api/sip/freepbx/sync", methods=["POST"])
def sip_freepbx_sync_api():
    data = request.json or {}
    usuario_ids = data.get("usuario_ids")
    if not isinstance(usuario_ids, list):
        usuario_ids = []
    usuario_ids = [int(i) for i in usuario_ids if _as_int(i, 0) > 0]
    convert_legacy = _as_bool(data.get("convert_legacy"), False)

    try:
        resultado = _sincronizar_usuarios_freepbx(
            apenas_ids=usuario_ids or None,
            convert_legacy=convert_legacy,
            strict=True,
        )
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Falha ao sincronizar no FreePBX: {str(exc)}"}), 500

    return jsonify({"ok": True, **resultado})

@app.route("/api/sip/me", methods=["GET"])
def sip_me():
    usuario_id_header = _as_int(request.headers.get("X-Usuario-Id"), 0)
    usuario_id_query = _as_int(request.args.get("usuario_id"), 0)
    usuario_id = usuario_id_header or usuario_id_query

    if usuario_id <= 0:
        return jsonify({"erro": "usuario_id obrigatorio"}), 400
    if usuario_id_header > 0 and usuario_id_query > 0 and usuario_id_header != usuario_id_query:
        return jsonify({"erro": "usuario_id divergente"}), 403

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT
                id,
                nome,
                login,
                ativo,
                sip_habilitado,
                sip_usuario,
                sip_senha,
                sip_ramal,
                data_cadastro
            FROM usuarios
            WHERE id = %s
            LIMIT 1
        """, (usuario_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"erro": "usuario nao encontrado"}), 404
        return jsonify({
            "usuario": _usuario_sip_dict(row),
            "config": _carregar_sip_config(cur),
        })
    finally:
        cur.close()
        conn.close()

@app.route("/api/sip/cert.pem", methods=["GET"])
def sip_cert_pem():
    try:
        endpoint = _sip_endpoint_ativo()
        if endpoint.get("scheme") != "wss":
            return jsonify({"erro": "O endpoint SIP ativo nao usa WSS/TLS."}), 400
        cert = _baixar_certificado_tls(endpoint["host"], endpoint["port"])
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Nao foi possivel baixar o certificado SIP: {str(exc)}"}), 500

    host = endpoint["host"].replace("/", "_")
    resp = Response(cert["pem"], mimetype="application/x-pem-file")
    resp.headers["Content-Disposition"] = f'attachment; filename="riobranco-sip-{host}.pem"'
    resp.headers["X-SIP-Cert-SHA1"] = cert["sha1"]
    return resp

@app.route("/api/sip/cert.crt", methods=["GET"])
def sip_cert_crt():
    try:
        endpoint = _sip_endpoint_ativo()
        if endpoint.get("scheme") != "wss":
            return jsonify({"erro": "O endpoint SIP ativo nao usa WSS/TLS."}), 400
        cert = _baixar_certificado_tls(endpoint["host"], endpoint["port"])
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Nao foi possivel baixar o certificado SIP: {str(exc)}"}), 500

    host = endpoint["host"].replace("/", "_")
    resp = Response(_cert_der_bytes(cert), mimetype="application/x-x509-ca-cert")
    resp.headers["Content-Disposition"] = f'attachment; filename="riobranco-sip-{host}.crt"'
    resp.headers["X-SIP-Cert-SHA1"] = cert["sha1"]
    return resp

@app.route("/api/app/cert.pem", methods=["GET"])
def app_cert_pem():
    try:
        cert = _carregar_certificado_local(_app_https_cert_path())
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Nao foi possivel carregar o certificado HTTPS: {str(exc)}"}), 500

    resp = Response(cert["pem"], mimetype="application/x-pem-file")
    resp.headers["Content-Disposition"] = 'attachment; filename="riobranco-web.pem"'
    resp.headers["X-App-Cert-SHA1"] = cert["sha1"]
    return resp

@app.route("/api/app/cert.crt", methods=["GET"])
def app_cert_crt():
    try:
        cert = _carregar_certificado_local(_app_https_cert_path())
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Nao foi possivel carregar o certificado HTTPS: {str(exc)}"}), 500

    resp = Response(_cert_der_bytes(cert), mimetype="application/x-x509-ca-cert")
    resp.headers["Content-Disposition"] = 'attachment; filename="riobranco-web.crt"'
    resp.headers["X-App-Cert-SHA1"] = cert["sha1"]
    return resp

@app.route("/api/ca/cert.pem", methods=["GET"])
def ca_cert_pem():
    try:
        cert = _carregar_ca_local(True)
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Nao foi possivel carregar o certificado CA: {str(exc)}"}), 500

    resp = Response(cert["pem"], mimetype="application/x-pem-file")
    resp.headers["Content-Disposition"] = 'attachment; filename="riobranco-ca.pem"'
    resp.headers["X-CA-Cert-SHA1"] = cert["sha1"]
    return resp

@app.route("/api/ca/cert.crt", methods=["GET"])
def ca_cert_crt():
    try:
        cert = _carregar_ca_local(True)
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Nao foi possivel carregar o certificado CA: {str(exc)}"}), 500

    resp = Response(_cert_der_bytes(cert), mimetype="application/x-x509-ca-cert")
    resp.headers["Content-Disposition"] = 'attachment; filename="riobranco-ca.crt"'
    resp.headers["X-CA-Cert-SHA1"] = cert["sha1"]
    return resp

@app.route("/api/certs.p12", methods=["GET"])
@app.route("/api/certs.pfx", methods=["GET"])
def certs_pkcs12_bundle():
    try:
        trust_items = _certificados_confianca_cliente()
        senha = _pkcs12_export_password()
        ext = "pfx" if request.path.endswith(".pfx") else "p12"
        nome = f"riobranco-certificados.{ext}"
        payload = _gerar_bundle_pkcs12([item["cert"] for item in trust_items], nome, senha)
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Nao foi possivel gerar o bundle PKCS#12: {str(exc)}"}), 500

    resp = Response(payload, mimetype="application/x-pkcs12")
    resp.headers["Content-Disposition"] = f'attachment; filename="{nome}"'
    resp.headers["X-Cert-Export-Password"] = senha
    resp.headers["X-Cert-Trust-Count"] = str(len(trust_items))
    return resp

@app.route("/api/sip/windows-install.ps1", methods=["GET"])
def sip_windows_install_script():
    try:
        endpoint = _sip_endpoint_ativo()
        if endpoint.get("scheme") != "wss":
            return jsonify({"erro": "O endpoint SIP ativo nao usa WSS/TLS."}), 400
        trust_items = _certificados_confianca_cliente()
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Nao foi possivel gerar o instalador do certificado: {str(exc)}"}), 500

    endpoint_ws = endpoint["ws_url"]
    var_lines = []
    item_lines = []
    for idx, item in enumerate(trust_items, start=1):
        pem_var = f"$cert{idx}Pem"
        pem_text = item["cert"]["pem"]
        filename = item["pem_filename"]
        is_ca_literal = "$true" if item["is_ca"] else "$false"
        var_lines.append(f"""{pem_var} = @'
{pem_text}'@""")
        item_lines.append(
            f"""  @{{ File = (Join-Path $env:TEMP '{filename}'); Label = '{item['label']}'; Thumbprint = '{item['cert']['sha1']}'; Pem = {pem_var}; IsCA = {is_ca_literal} }}"""
        )

    trust_mode = "CA interna unica" if len(trust_items) == 1 and trust_items[0]["is_ca"] else "certificados do servidor"
    script = f"""$ErrorActionPreference = 'Stop'
{chr(10).join(var_lines)}
$downloads = @(
{chr(10).join(item_lines)}
)
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

foreach ($item in $downloads) {{
  $stores = if ($item.IsCA) {{
    if ($isAdmin) {{ @('Cert:\\LocalMachine\\Root') }} else {{ @('Cert:\\CurrentUser\\Root') }}
  }} else {{
    if ($isAdmin) {{ @('Cert:\\LocalMachine\\Root', 'Cert:\\LocalMachine\\TrustedPeople') }} else {{ @('Cert:\\CurrentUser\\Root', 'Cert:\\CurrentUser\\TrustedPeople') }}
  }}
  Set-Content -Path $item.File -Value $item.Pem -NoNewline -Encoding ascii
  $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($item.File)
  foreach ($store in $stores) {{
    $existing = Get-ChildItem -Path $store | Where-Object {{ $_.Thumbprint -eq $cert.Thumbprint }}
    if (-not $existing) {{
      Import-Certificate -FilePath $item.File -CertStoreLocation $store | Out-Null
    }}
  }}
  Write-Host "Certificado importado: $($item.Label) - $($cert.Thumbprint)"
}}

Write-Host "Certificados do RioBranco importados com sucesso."
Write-Host "Modo de confianca: {trust_mode}"
Write-Host "Endpoint WSS: {endpoint_ws}"
"""
    resp = Response(script, mimetype="text/plain; charset=utf-8")
    resp.headers["Content-Disposition"] = 'attachment; filename="instalar-certificado-sip-riobranco.ps1"'
    return resp

@app.route("/api/sip/linux-install.sh", methods=["GET"])
def sip_linux_install_script():
    try:
        endpoint = _sip_endpoint_ativo()
        if endpoint.get("scheme") != "wss":
            return jsonify({"erro": "O endpoint SIP ativo nao usa WSS/TLS."}), 400
        trust_items = _certificados_confianca_cliente()
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Nao foi possivel gerar o script Linux: {str(exc)}"}), 500

    endpoint_ws = endpoint["ws_url"]
    assign_lines = []
    write_lines = []
    firefox_import_lines = []
    chromium_import_lines = []
    persist_vars = []
    for idx, item in enumerate(trust_items, start=1):
        file_var = f"CERT_{idx}_FILE"
        label_var = f"CERT_{idx}_LABEL"
        trust_var = f"CERT_{idx}_FLAGS"
        heredoc_name = f"EOF_RIOBRANCO_CERT_{idx}"

        assign_lines.append(f'{file_var}="${{HOME}}/{item["pem_filename"]}"')
        assign_lines.append(f'{label_var}="{item["label"]}"')
        assign_lines.append(f'{trust_var}="{"C,," if item["is_ca"] else "P,,"}"')

        write_lines.append(f'  cat >"${{{file_var}}}" <<\'{heredoc_name}\'')
        write_lines.append(item["cert"]["pem"].rstrip("\n"))
        write_lines.append(heredoc_name)

        firefox_import_lines.append(f'        import_nss_cert "$profile" "${{{label_var}}}" "${{{file_var}}}" "${{{trust_var}}}"')
        chromium_import_lines.append(f'  import_nss_cert "$pki_dir" "${{{label_var}}}" "${{{file_var}}}" "${{{trust_var}}}"')
        persist_vars.append(f"${{{file_var}}}")

    trust_mode = "CA interna unica" if len(trust_items) == 1 and trust_items[0]["is_ca"] else "certificados do servidor"
    script = f"""#!/bin/sh
set -eu

SIP_ENDPOINT="{endpoint_ws}"
TRUST_MODE="{trust_mode}"

{chr(10).join(assign_lines)}

ensure_certutil() {{
  if command -v certutil >/dev/null 2>&1; then
    return
  fi

  if command -v tce-load >/dev/null 2>&1; then
    echo "certutil nao encontrado. Tentando instalar nss-tools no TinyCore..."
    tce-load -wi nss-tools >/dev/null 2>&1 || true
  fi

  if ! command -v certutil >/dev/null 2>&1; then
    echo "Instale o pacote nss-tools/libnss3-tools e execute novamente." >&2
    exit 1
  fi
}}

browser_open() {{
  pgrep -f 'firefox|chromium|chrome' >/dev/null 2>&1
}}

write_certificates() {{
{chr(10).join(write_lines)}
}}

import_nss_cert() {{
  db="$1"
  label="$2"
  cert_file="$3"
  trust_flags="$4"
  mkdir -p "$db"
  certutil -d "sql:$db" -N --empty-password >/dev/null 2>&1 || true
  certutil -d "sql:$db" -D -n "$label" >/dev/null 2>&1 || true
  certutil -d "sql:$db" -A -n "$label" -t "$trust_flags" -i "$cert_file"
}}

import_firefox_profiles() {{
  imported=0
  firefox_dir="${{HOME}}/.mozilla/firefox"
  if [ ! -d "$firefox_dir" ]; then
    return 0
  fi

  for profile in "$firefox_dir"/*; do
    [ -d "$profile" ] || continue
    profile_name="$(basename "$profile")"
    case "$profile_name" in
      *.default*|*.esr*|*.release*)
{chr(10).join(firefox_import_lines)}
        echo "Firefox/NSS atualizado: $profile"
        imported=1
        ;;
    esac
  done

  if [ "$imported" -eq 0 ]; then
    echo "Nenhum perfil Firefox ESR encontrado em $firefox_dir."
  fi
}}

import_chromium_store() {{
  pki_dir="${{HOME}}/.pki/nssdb"
{chr(10).join(chromium_import_lines)}
  echo "NSS do Chromium/Chrome atualizado: $pki_dir"
}}

persist_tinycore() {{
  if ! command -v filetool.sh >/dev/null 2>&1; then
    return
  fi

  backup_list="/opt/.filetool.lst"
  for item in {(" ".join(persist_vars))} "${{HOME}}/.mozilla" "${{HOME}}/.pki"; do
    [ -e "$item" ] || continue
    grep -qxF "$item" "$backup_list" 2>/dev/null || echo "$item" >> "$backup_list"
  done
  filetool.sh -b >/dev/null 2>&1 || true
}}

if browser_open; then
  echo "Feche Firefox/Chrome/Chromium antes de executar este script." >&2
  exit 1
fi

ensure_certutil
write_certificates
import_firefox_profiles
import_chromium_store
persist_tinycore

echo "Certificados importados com sucesso."
echo "Modo de confianca: $TRUST_MODE"
echo "Endpoint WSS: $SIP_ENDPOINT"
echo "Reabra o Firefox ESR e acesse a aplicacao em: {request.host_url.rstrip('/')}"
"""
    resp = Response(script, mimetype="text/x-shellscript; charset=utf-8")
    resp.headers["Content-Disposition"] = 'attachment; filename="instalar-certificados-riobranco-linux.sh"'
    return resp

@app.route("/api/sip/apple.mobileconfig", methods=["GET"])
def sip_apple_mobileconfig():
    try:
        endpoint = _sip_endpoint_ativo()
        if endpoint.get("scheme") != "wss":
            return jsonify({"erro": "O endpoint SIP ativo nao usa WSS/TLS."}), 400
        trust_items = _certificados_confianca_cliente()
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Nao foi possivel gerar o perfil iPhone/iPad: {str(exc)}"}), 500

    profile_uuid = str(uuid.uuid4()).upper()
    payloads_xml = []
    for item in trust_items:
        payload_uuid = str(uuid.uuid4()).upper()
        payloads_xml.append(f"""    <dict>
      <key>PayloadCertificateFileName</key>
      <string>{item['pem_filename']}</string>
      <key>PayloadContent</key>
      <data>{item['cert']['der_b64']}</data>
      <key>PayloadDescription</key>
      <string>{item['mobileconfig_desc']}</string>
      <key>PayloadDisplayName</key>
      <string>{item['mobileconfig_name']}</string>
      <key>PayloadIdentifier</key>
      <string>{item['mobileconfig_id']}</string>
      <key>PayloadType</key>
      <string>com.apple.security.root</string>
      <key>PayloadUUID</key>
      <string>{payload_uuid}</string>
      <key>PayloadVersion</key>
      <integer>1</integer>
    </dict>""")
    profile_desc = "Instala a CA interna do RioBranco." if len(trust_items) == 1 and trust_items[0]["is_ca"] else "Instala os certificados HTTPS e SIP/WSS do RioBranco."
    profile = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>PayloadContent</key>
  <array>
{chr(10).join(payloads_xml)}
  </array>
  <key>PayloadDescription</key>
  <string>{profile_desc}</string>
  <key>PayloadDisplayName</key>
  <string>RioBranco Certificados</string>
  <key>PayloadIdentifier</key>
  <string>br.com.riobranco.profile.certificados</string>
  <key>PayloadOrganization</key>
  <string>RioBranco</string>
  <key>PayloadRemovalDisallowed</key>
  <false/>
  <key>PayloadType</key>
  <string>Configuration</string>
  <key>PayloadUUID</key>
  <string>{profile_uuid}</string>
  <key>PayloadVersion</key>
  <integer>1</integer>
</dict>
</plist>
"""
    resp = Response(profile, mimetype="application/x-apple-aspen-config; charset=utf-8")
    resp.headers["Content-Disposition"] = 'attachment; filename="riobranco-certificados.mobileconfig"'
    return resp

# =========================================================
# (4) DASHBOARD
# =========================================================
@app.route("/api/dashboard")
def dashboard():
    _limpar_fretes_finalizados_expirados()
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT status, COUNT(*) as total
        FROM fretes
        GROUP BY status
    """)
    dados = cursor.fetchall()

    resumo = {
        "chegada": 0,
        "descarregado": 0,
        "liberado": 0,
        "carregando": 0,
        "carregado": 0,
        "entregando": 0,
        "retornando": 0,
        "paradoVasio": 0,
        "paradoCarregado": 0
    }

    for row in dados:
        if row["status"] in resumo:
            resumo[row["status"]] = row["total"]

    cursor.close()
    conn.close()
    return jsonify(resumo)

@app.route("/api/dashboard_estoque", methods=["GET"])
def dashboard_estoque():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            codigo_barras,
            nome_produto,
            COALESCE(SUM(CASE WHEN tipo_movimento = 'saida' THEN -quantidade ELSE quantidade END), 0) AS quantidade_atual,
            MAX(data_registro) AS ultima_movimentacao,
            (
                SELECT e2.valor_unitario
                FROM estoque_movimentos e2
                WHERE
                    COALESCE(e2.codigo_barras, '') = COALESCE(e.codigo_barras, '')
                    AND COALESCE(e2.nome_produto, '') = COALESCE(e.nome_produto, '')
                ORDER BY e2.id DESC
                LIMIT 1
            ) AS ultimo_valor
        FROM estoque_movimentos e
        GROUP BY codigo_barras, nome_produto
        HAVING ABS(quantidade_atual) > 0
        ORDER BY nome_produto ASC, codigo_barras ASC
    """)
    rows = cur.fetchall() or []
    cur.close()
    conn.close()
    return jsonify([
        {
            "codigo_barras": _as_str(r.get("codigo_barras")),
            "nome_produto": _as_str(r.get("nome_produto")),
            "quantidade_atual": _as_float(r.get("quantidade_atual"), 0.0),
            "ultimo_valor": _as_float(r.get("ultimo_valor"), 0.0),
            "ultima_movimentacao": _fmt_dt(r.get("ultima_movimentacao")),
        } for r in rows
    ])

@app.route("/api/estoque", methods=["POST"])
def criar_movimento_estoque():
    usuario = _usuario_ator_req()
    data = request.json or {}
    codigo_barras = _normalizar_codigo_barras(data.get("codigo_barras"))
    codigo_produto_nfe = _as_str(data.get("codigo_produto_nfe"))
    numero_nota = _as_str(data.get("numero_nota"))
    nome_produto = _as_str(data.get("nome_produto"))
    quantidade = _as_float(data.get("quantidade"), 0.0)
    valor_unitario = _as_float(data.get("valor_unitario"), 0.0)
    tipo_movimento = _as_str(data.get("tipo_movimento")).lower() or "entrada"
    origem_setor = _as_str(data.get("origem_setor")) or "Fabrica"
    destino_setor = _as_str(data.get("destino_setor")) or "Almoxarifado"
    referencia_tipo = _as_str(data.get("referencia_tipo"))
    referencia_id = _as_int(data.get("referencia_id"), 0) if data.get("referencia_id") not in (None, "") else None
    unidade = _as_str(data.get("unidade"))
    if tipo_movimento not in ("entrada", "saida"):
        tipo_movimento = "entrada"

    if not numero_nota and codigo_barras:
        numero_nota = codigo_barras
    if not nome_produto:
        return jsonify({"erro": "nome_produto é obrigatório"}), 400
    if quantidade <= 0:
        return jsonify({"erro": "quantidade inválida"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        produto, produto_criado = _obter_ou_criar_produto_estoque(
            cur,
            codigo_barras=codigo_barras,
            codigo_produto_nfe=codigo_produto_nfe,
            nome_produto=nome_produto,
            unidade=unidade,
            origem_cadastro=_as_str(data.get("origem_cadastro")) or "manual",
        )
        cur.execute(
            """
            INSERT INTO estoque_movimentos
                (
                    codigo_barras, numero_nota, nome_produto, quantidade, valor_unitario, tipo_movimento,
                    origem_setor, destino_setor, referencia_tipo, referencia_id, usuario_registro
                )
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                codigo_barras,
                numero_nota,
                nome_produto,
                quantidade,
                valor_unitario,
                tipo_movimento,
                origem_setor,
                destino_setor,
                referencia_tipo,
                referencia_id,
                usuario,
            )
        )
        movimento_id = cur.lastrowid
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return jsonify({
        "ok": True,
        "id": movimento_id,
        "produto": _produto_estoque_publico(produto),
        "produto_criado": bool(produto_criado),
    })

@app.route("/api/estoque", methods=["GET"])
def listar_movimentos_estoque():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            id,
            codigo_barras,
            numero_nota,
            nome_produto,
            quantidade,
            valor_unitario,
            tipo_movimento,
            origem_setor,
            destino_setor,
            referencia_tipo,
            referencia_id,
            usuario_registro,
            data_registro
        FROM estoque_movimentos
        ORDER BY id DESC
        LIMIT 500
    """)
    rows = cur.fetchall() or []
    cur.close()
    conn.close()
    return jsonify([
        {
            "id": _as_int(r.get("id"), 0),
            "codigo_barras": _as_str(r.get("codigo_barras")),
            "numero_nota": _as_str(r.get("numero_nota")),
            "nome_produto": _as_str(r.get("nome_produto")),
            "quantidade": _as_float(r.get("quantidade"), 0.0),
            "valor_unitario": _as_float(r.get("valor_unitario"), 0.0),
            "tipo_movimento": _as_str(r.get("tipo_movimento")) or "entrada",
            "origem_setor": _as_str(r.get("origem_setor")),
            "destino_setor": _as_str(r.get("destino_setor")),
            "referencia_tipo": _as_str(r.get("referencia_tipo")),
            "referencia_id": _as_int(r.get("referencia_id"), 0),
            "usuario_registro": _as_str(r.get("usuario_registro")),
            "data_registro": _fmt_dt(r.get("data_registro")),
        } for r in rows
    ])

@app.route("/api/estoque/<int:movimento_id>", methods=["PUT"])
def atualizar_movimento_estoque(movimento_id):
    usuario = _usuario_ator_req()
    data = request.json or {}
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT id, codigo_barras, numero_nota, nome_produto, quantidade, valor_unitario,
                   tipo_movimento, origem_setor, destino_setor
            FROM estoque_movimentos
            WHERE id=%s
            LIMIT 1
        """, (movimento_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"erro": "lancamento de estoque nao encontrado"}), 404

        codigo_barras = _normalizar_codigo_barras(data.get("codigo_barras")) if "codigo_barras" in data else _as_str(row.get("codigo_barras"))
        numero_nota = _as_str(data.get("numero_nota")) if "numero_nota" in data else _as_str(row.get("numero_nota"))
        nome_produto = _as_str(data.get("nome_produto")) if "nome_produto" in data else _as_str(row.get("nome_produto"))
        quantidade = _as_float(data.get("quantidade"), _as_float(row.get("quantidade"), 0.0)) if "quantidade" in data else _as_float(row.get("quantidade"), 0.0)
        valor_unitario = _as_float(data.get("valor_unitario"), _as_float(row.get("valor_unitario"), 0.0)) if "valor_unitario" in data else _as_float(row.get("valor_unitario"), 0.0)
        tipo_movimento = _as_str(data.get("tipo_movimento")).lower() if "tipo_movimento" in data else _as_str(row.get("tipo_movimento")).lower()
        origem_setor = _as_str(data.get("origem_setor")) if "origem_setor" in data else _as_str(row.get("origem_setor"))
        destino_setor = _as_str(data.get("destino_setor")) if "destino_setor" in data else _as_str(row.get("destino_setor"))

        if not nome_produto:
            return jsonify({"erro": "nome_produto e obrigatorio"}), 400
        if quantidade <= 0:
            return jsonify({"erro": "quantidade invalida"}), 400
        if tipo_movimento not in ("entrada", "saida"):
            tipo_movimento = "entrada"

        cur.execute("""
            UPDATE estoque_movimentos
            SET codigo_barras=%s, numero_nota=%s, nome_produto=%s, quantidade=%s, valor_unitario=%s,
                tipo_movimento=%s, origem_setor=%s, destino_setor=%s, usuario_registro=%s
            WHERE id=%s
        """, (
            codigo_barras,
            numero_nota,
            nome_produto,
            quantidade,
            valor_unitario,
            tipo_movimento,
            origem_setor,
            destino_setor,
            usuario,
            movimento_id,
        ))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        cur.close()
        conn.close()

@app.route("/api/estoque/<int:movimento_id>", methods=["DELETE"])
def excluir_movimento_estoque(movimento_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM estoque_movimentos WHERE id=%s LIMIT 1", (movimento_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"erro": "lancamento de estoque nao encontrado"}), 404
        cur.execute("DELETE FROM estoque_movimentos WHERE id=%s", (movimento_id,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        cur.close()
        conn.close()

@app.route("/api/estoque/saldo", methods=["GET"])
def saldo_estoque():
    return dashboard_estoque()

@app.route("/api/estoque/produtos", methods=["GET"])
def listar_produtos_estoque():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            id,
            codigo_barras,
            codigo_produto_nfe,
            nome_produto,
            unidade,
            embalagem_tipo_padrao,
            fator_embalagem_padrao,
            origem_cadastro,
            criado_em,
            atualizado_em
        FROM estoque_produtos
        ORDER BY nome_produto ASC, id ASC
    """)
    rows = cur.fetchall() or []
    cur.close()
    conn.close()
    return jsonify([_produto_estoque_publico(r) for r in rows])

@app.route("/api/estoque/produtos", methods=["POST"])
def criar_produto_estoque():
    data = request.json or {}
    codigo_barras = _normalizar_codigo_barras(data.get("codigo_barras"))
    codigo_produto_nfe = _as_str(data.get("codigo_produto_nfe"))
    nome_produto = _as_str(data.get("nome_produto"))
    embalagem_tipo_padrao = _as_str(data.get("embalagem_tipo_padrao") or data.get("embalagem_tipo"))
    fator_embalagem_padrao = _as_float(data.get("fator_embalagem_padrao"), _as_float(data.get("fator_embalagem"), 0.0))
    if not (codigo_barras or codigo_produto_nfe or nome_produto):
        return jsonify({"erro": "informe ao menos codigo de barras, codigo NF-e ou nome do produto"}), 400
    if not embalagem_tipo_padrao:
        return jsonify({"erro": "embalagem padrao e obrigatoria"}), 400
    if fator_embalagem_padrao <= 0:
        return jsonify({"erro": "unidades por embalagem deve ser maior que zero"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        existente = _buscar_produto_estoque(cur, codigo_barras=codigo_barras, codigo_produto_nfe=codigo_produto_nfe, nome_produto=nome_produto)
        if existente:
            return jsonify({"erro": "ja existe cadastro para este produto"}), 409
        cur.execute("""
            INSERT INTO estoque_produtos
                (codigo_barras, codigo_produto_nfe, nome_produto, unidade, embalagem_tipo_padrao, fator_embalagem_padrao, origem_cadastro)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s)
        """, (
            codigo_barras,
            codigo_produto_nfe,
            nome_produto,
            embalagem_tipo_padrao,
            embalagem_tipo_padrao,
            fator_embalagem_padrao,
            "manual",
        ))
        produto_id = cur.lastrowid
        conn.commit()
        cur.execute("""
            SELECT id, codigo_barras, codigo_produto_nfe, nome_produto, unidade,
                   embalagem_tipo_padrao, fator_embalagem_padrao, origem_cadastro, criado_em, atualizado_em
            FROM estoque_produtos
            WHERE id=%s
            LIMIT 1
        """, (produto_id,))
        row = cur.fetchone()
        return jsonify({"ok": True, "produto": _produto_estoque_publico(row)})
    finally:
        cur.close()
        conn.close()

@app.route("/api/estoque/produtos/<int:produto_id>", methods=["PUT"])
def atualizar_produto_estoque(produto_id):
    data = request.json or {}
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT id, codigo_barras, codigo_produto_nfe, nome_produto, unidade,
                   embalagem_tipo_padrao, fator_embalagem_padrao, origem_cadastro, criado_em, atualizado_em
            FROM estoque_produtos
            WHERE id=%s
            LIMIT 1
        """, (produto_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"erro": "produto nao encontrado"}), 404

        codigo_barras = _normalizar_codigo_barras(data.get("codigo_barras")) if "codigo_barras" in data else _normalizar_codigo_barras(row.get("codigo_barras"))
        codigo_produto_nfe = _as_str(data.get("codigo_produto_nfe")) if "codigo_produto_nfe" in data else _as_str(row.get("codigo_produto_nfe"))
        nome_produto = _as_str(data.get("nome_produto")) if "nome_produto" in data else _as_str(row.get("nome_produto"))
        embalagem_tipo_padrao = _as_str(data.get("embalagem_tipo_padrao") or data.get("embalagem_tipo")) if ("embalagem_tipo_padrao" in data or "embalagem_tipo" in data) else _as_str(row.get("embalagem_tipo_padrao"))
        fator_embalagem_padrao = _as_float(data.get("fator_embalagem_padrao"), _as_float(data.get("fator_embalagem"), 0.0)) if ("fator_embalagem_padrao" in data or "fator_embalagem" in data) else _as_float(row.get("fator_embalagem_padrao"), 0.0)

        if not (codigo_barras or codigo_produto_nfe or nome_produto):
            return jsonify({"erro": "informe ao menos codigo de barras, codigo NF-e ou nome do produto"}), 400
        if not embalagem_tipo_padrao:
            return jsonify({"erro": "embalagem padrao e obrigatoria"}), 400
        if fator_embalagem_padrao <= 0:
            return jsonify({"erro": "unidades por embalagem deve ser maior que zero"}), 400

        cur.execute("""
            UPDATE estoque_produtos
            SET codigo_barras=%s,
                codigo_produto_nfe=%s,
                nome_produto=%s,
                unidade=%s,
                embalagem_tipo_padrao=%s,
                fator_embalagem_padrao=%s
            WHERE id=%s
        """, (
            codigo_barras,
            codigo_produto_nfe,
            nome_produto,
            embalagem_tipo_padrao,
            embalagem_tipo_padrao,
            fator_embalagem_padrao,
            produto_id,
        ))
        conn.commit()
        cur.execute("""
            SELECT id, codigo_barras, codigo_produto_nfe, nome_produto, unidade,
                   embalagem_tipo_padrao, fator_embalagem_padrao, origem_cadastro, criado_em, atualizado_em
            FROM estoque_produtos
            WHERE id=%s
            LIMIT 1
        """, (produto_id,))
        row = cur.fetchone()
        return jsonify({"ok": True, "produto": _produto_estoque_publico(row)})
    finally:
        cur.close()
        conn.close()

@app.route("/api/estoque/produtos/<int:produto_id>", methods=["DELETE"])
def excluir_produto_estoque(produto_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM estoque_produtos WHERE id=%s LIMIT 1", (produto_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"erro": "produto nao encontrado"}), 404
        cur.execute("DELETE FROM estoque_produtos WHERE id=%s", (produto_id,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        cur.close()
        conn.close()

@app.route("/api/estoque/conferencias", methods=["GET"])
def listar_conferencias_estoque():
    status_filtro = _as_str(request.args.get("status")).lower()
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    sql = """
        SELECT
            c.*,
            COUNT(i.id) AS total_itens,
            COALESCE(SUM(i.quantidade_nfe), 0) AS total_quantidade_nfe,
            COALESCE(SUM(i.quantidade_conferida), 0) AS total_quantidade_conferida
        FROM estoque_conferencias c
        LEFT JOIN estoque_conferencia_itens i ON i.conferencia_id = c.id
    """
    params = []
    if status_filtro:
        sql += " WHERE c.status=%s"
        params.append(status_filtro)
    sql += " GROUP BY c.id ORDER BY CASE WHEN c.status='pendente' THEN 0 ELSE 1 END, c.id DESC"
    cur.execute(sql, tuple(params))
    rows = cur.fetchall() or []
    cur.close()
    conn.close()
    return jsonify([_estoque_conferencia_publica(r) for r in rows])

@app.route("/api/estoque/conferencias/<int:conferencia_id>", methods=["GET"])
def detalhar_conferencia_estoque(conferencia_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    conferencia = _carregar_conferencia_estoque(cur, conferencia_id)
    if not conferencia:
        cur.close()
        conn.close()
        return jsonify({"erro": "conferencia nao encontrada"}), 404
    itens = _listar_itens_conferencia_estoque(cur, conferencia_id)
    cur.close()
    conn.close()
    return jsonify({
        "conferencia": _estoque_conferencia_publica(conferencia),
        "itens": [_estoque_conferencia_item_publico(item) for item in itens],
    })

@app.route("/api/estoque/nfe/preview", methods=["POST"])
def preview_nfe_estoque():
    try:
        preview = _preview_nfe_estoque_requisicao()
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Falha ao ler a NF-e: {str(exc)}"}), 500

    return jsonify({
        "ok": True,
        "preview": preview,
        "warnings": preview.get("warnings") or [],
    })


@app.route("/api/estoque/nfe/portal_retorno", methods=["POST"])
def portal_retorno_nfe_estoque():
    html_text = _as_str(request.form.get("html_text") or request.form.get("html") or request.get_data(as_text=True))
    chave_acesso_esperada = _normalizar_chave_acesso_nfe(request.form.get("chave_acesso_esperada"))
    origin = _as_str(request.form.get("origin")).strip()
    if not origin:
        origin = _as_str(request.host_url).rstrip("/")

    try:
        preview = _parse_nfe_portal_html(
            html_text,
            arquivo_origem=_as_str(request.form.get("arquivo_origem")) or "consulta_nfe_portal.html",
        )
        chave_preview = _normalizar_chave_acesso_nfe(preview.get("chave_acesso"))
        if chave_acesso_esperada:
            if chave_preview and chave_preview != chave_acesso_esperada:
                raise ValueError("a chave retornada pelo portal nao confere com a chave bipada")
            if not chave_preview:
                preview["chave_acesso"] = chave_acesso_esperada
    except ValueError as exc:
        payload = {"type": "riobranco_nfe_portal_preview_erro", "erro": str(exc)}
        titulo = "Falha ao importar consulta NF-e"
        mensagem = str(exc)
    except Exception as exc:
        payload = {"type": "riobranco_nfe_portal_preview_erro", "erro": f"Falha ao importar o retorno do portal: {str(exc)}"}
        titulo = "Falha ao importar consulta NF-e"
        mensagem = payload["erro"]
    else:
        payload = {
            "type": "riobranco_nfe_portal_preview",
            "preview": preview,
            "warnings": preview.get("warnings") or [],
        }
        titulo = "Consulta NF-e enviada ao Rio Branco"
        mensagem = "Os dados foram enviados para a tela principal. Esta aba pode ser fechada."

    payload_json = json.dumps(payload, ensure_ascii=False)
    origin_json = json.dumps(origin, ensure_ascii=False)
    titulo_html = html_lib.escape(titulo)
    mensagem_html = html_lib.escape(mensagem)
    return Response(
        f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>{titulo_html}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="font-family:Arial,sans-serif;padding:24px">
  <h2 style="margin-top:0">{titulo_html}</h2>
  <p>{mensagem_html}</p>
  <script>
  (function() {{
    const payload = {payload_json};
    const targetOrigin = {origin_json};
    try {{
      if (window.opener && !window.opener.closed) {{
        window.opener.postMessage(payload, targetOrigin || "*");
      }}
    }} catch (err) {{
      console.warn("postMessage portal retorno erro:", err);
    }}
    try {{
      localStorage.setItem("riobranco_nfe_portal_preview", JSON.stringify({{
        at: Date.now(),
        payload: payload
      }}));
    }} catch (err) {{
      console.warn("localStorage portal retorno erro:", err);
    }}
    setTimeout(function() {{
      try {{ window.close(); }} catch (err) {{}}
    }}, 250);
  }})();
  </script>
</body>
</html>""",
        mimetype="text/html",
    )

@app.route("/api/estoque/nfe/ocr", methods=["POST"])
def ocr_nfe_estoque():
    try:
        conteudo, arquivo_origem, _mimetype = _ler_arquivo_imagem_requisicao()
        ocr = _ocr_nfe_imagem_bytes(conteudo, arquivo_origem=arquivo_origem)
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 503
    except Exception as exc:
        return jsonify({"erro": f"Falha ao ler a foto da nota: {str(exc)}"}), 500

    return jsonify({
        "ok": True,
        "ocr": ocr,
        "warnings": ocr.get("warnings") or [],
    })

@app.route("/api/estoque/nfe/ocr_itens", methods=["POST"])
def ocr_itens_nfe_estoque():
    try:
        conteudo, arquivo_origem, _mimetype = _ler_arquivo_imagem_requisicao()
        preview = _ocr_itens_nfe_imagem_bytes(conteudo, arquivo_origem=arquivo_origem)
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 503
    except Exception as exc:
        return jsonify({"erro": f"Falha ao ler os itens da nota por OCR: {str(exc)}"}), 500

    return jsonify({
        "ok": True,
        "preview": preview,
        "warnings": preview.get("warnings") or [],
    })

@app.route("/api/estoque/nfe/azure_itens", methods=["POST"])
def azure_itens_nfe_estoque():
    try:
        conteudo, arquivo_origem, _mimetype = _ler_arquivo_imagem_requisicao()
        preview = _azure_docint_nfe_itens_preview(conteudo, arquivo_origem=arquivo_origem)
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 502
    except Exception as exc:
        return jsonify({"erro": f"Falha ao analisar a imagem no Azure: {str(exc)}"}), 500

    return jsonify({
        "ok": True,
        "preview": preview,
        "warnings": preview.get("warnings") or [],
    })

@app.route("/api/estoque/nfe/preview_dfe", methods=["POST"])
def preview_nfe_estoque_dfe():
    payload = request.get_json(silent=True) or {}
    chave_acesso = _normalizar_chave_acesso_nfe(payload.get("chave_acesso"))
    manifestar_automaticamente = payload.get("manifestar_automaticamente")
    if len(chave_acesso) != 44:
        return jsonify({"erro": "a chave de acesso da NF-e precisa ter 44 digitos."}), 400

    try:
        preview, resultado = _preview_nfe_estoque_por_dfe(
            chave_acesso,
            arquivo_origem="NFeDistribuicaoDFe",
            manifestar_automaticamente=manifestar_automaticamente,
        )
    except (RuntimeError, ValueError) as exc:
        return jsonify({"erro": str(exc), "limite_consultas": _nfe_dfe_limite_status()}), 400
    except Exception as exc:
        return jsonify({"erro": f"Falha ao consultar DF-e: {str(exc)}"}), 500

    return jsonify({
        "ok": True,
        "preview": preview,
        "preview_tipo": preview.get("preview_tipo") or "completo",
        "limitation_message": preview.get("limitation_message") or "",
        "warnings": preview.get("warnings") or [],
        "dfe": _nfe_resumo_distribuicao_publico(resultado),
        "limite_consultas": resultado.get("limite_consultas") or _nfe_dfe_limite_status(),
    })

@app.route("/api/estoque/nfe/import", methods=["POST"])
def importar_nfe_estoque():
    try:
        payload = request.get_json(silent=True) or {}
        preview_payload = payload.get("preview") if isinstance(payload.get("preview"), dict) else None
        if preview_payload is not None:
            nfe_preview = _normalizar_preview_nfe(preview_payload)
            chave_acesso_esperada = _normalizar_chave_acesso_nfe(payload.get("chave_acesso_esperada"))
            chave_preview = _normalizar_chave_acesso_nfe(nfe_preview.get("chave_acesso"))
            if chave_acesso_esperada:
                if chave_preview and chave_preview != chave_acesso_esperada:
                    raise ValueError("a chave bipada nao confere com os dados editados da NF-e")
                if not chave_preview:
                    nfe_preview["chave_acesso"] = chave_acesso_esperada
        else:
            nfe_preview = _preview_nfe_estoque_requisicao()
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400

    try:
        resultado = _persistir_preview_nfe_estoque(nfe_preview)
    except ValueError as exc:
        msg = str(exc)
        status_code = 409 if ("ja " in msg.lower() or "consolidad" in msg.lower()) else 400
        return jsonify({"erro": msg}), status_code

    return jsonify({
        "ok": True,
        "conferencia": resultado.get("conferencia"),
        "itens": resultado.get("itens") or [],
        "produtos_criados": _as_int(resultado.get("produtos_criados"), 0),
    })

@app.route("/api/estoque/conferencias/<int:conferencia_id>/confirmar", methods=["POST"])
def confirmar_conferencia_estoque(conferencia_id):
    usuario = _usuario_ator_req()
    data = request.json or {}
    origem_setor = _as_str(data.get("origem_setor")) or "Fabrica"
    destino_setor = _as_str(data.get("destino_setor")) or "Almoxarifado"
    itens_payload = data.get("itens") if isinstance(data.get("itens"), list) else []
    qtd_por_item = {
        _as_int(item.get("id"), 0): _as_float(item.get("quantidade_conferida"), 0.0)
        for item in itens_payload
        if _as_int(item.get("id"), 0) > 0
    }
    produto_por_item = {
        _as_int(item.get("id"), 0): _as_int(item.get("produto_id"), 0)
        for item in itens_payload
        if _as_int(item.get("id"), 0) > 0
    }

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        conferencia = _carregar_conferencia_estoque(cur, conferencia_id)
        if not conferencia:
            return jsonify({"erro": "conferencia nao encontrada"}), 404
        if _as_str(conferencia.get("status")) == "consolidado":
            return jsonify({"erro": "conferencia ja consolidada"}), 409

        itens = _listar_itens_conferencia_estoque(cur, conferencia_id)
        total_lancado = 0
        for item in itens:
            item_id = _as_int(item.get("id"), 0)
            quantidade_conferida = qtd_por_item.get(item_id, _as_float(item.get("quantidade_conferida"), 0.0))
            produto_id_selecionado = produto_por_item.get(item_id, _as_int(item.get("produto_id"), 0))
            produto_escolhido = _carregar_produto_estoque_por_id(cur, produto_id_selecionado) if produto_id_selecionado > 0 else None
            nome_produto_final = _as_str(produto_escolhido.get("nome_produto")) if produto_escolhido else _as_str(item.get("nome_produto"))
            codigo_barras_final = _normalizar_codigo_barras(produto_escolhido.get("codigo_barras")) if produto_escolhido else _normalizar_codigo_barras(item.get("codigo_barras"))
            codigo_produto_nfe_final = _as_str(produto_escolhido.get("codigo_produto_nfe")) if produto_escolhido else _as_str(item.get("codigo_produto_nfe"))
            if quantidade_conferida <= 0:
                quantidade_conferida = _as_float(item.get("quantidade_nfe"), 0.0)

            cur.execute(
                """
                UPDATE estoque_conferencia_itens
                SET quantidade_conferida=%s,
                    produto_id=%s,
                    nome_produto=%s,
                    codigo_barras=%s,
                    codigo_produto_nfe=%s
                WHERE id=%s
                """,
                (
                    quantidade_conferida,
                    produto_id_selecionado or None,
                    nome_produto_final,
                    codigo_barras_final,
                    codigo_produto_nfe_final,
                    item_id,
                )
            )

            if quantidade_conferida <= 0:
                continue

            cur.execute("""
                INSERT INTO estoque_movimentos
                    (
                        codigo_barras, numero_nota, nome_produto, quantidade, valor_unitario, tipo_movimento,
                        origem_setor, destino_setor, referencia_tipo, referencia_id, usuario_registro
                    )
                VALUES
                    (%s, %s, %s, %s, %s, 'entrada', %s, %s, 'conferencia_nfe', %s, %s)
            """, (
                codigo_barras_final,
                _as_str(conferencia.get("numero_nota")),
                nome_produto_final,
                quantidade_conferida,
                _as_float(item.get("valor_unitario"), 0.0),
                origem_setor,
                destino_setor,
                conferencia_id,
                usuario,
            ))
            movimento_id = cur.lastrowid
            total_lancado += 1
            cur.execute("""
                UPDATE estoque_conferencia_itens
                SET estoque_movimento_id=%s, consolidado_em=NOW()
                WHERE id=%s
            """, (movimento_id, item_id))

        if total_lancado <= 0:
            return jsonify({"erro": "nenhum item valido para consolidar"}), 400

        cur.execute("""
            UPDATE estoque_conferencias
            SET
                status='consolidado',
                origem_setor=%s,
                destino_setor=%s,
                recebido_por=%s,
                confirmado_em=NOW()
            WHERE id=%s
        """, (origem_setor, destino_setor, usuario, conferencia_id))

        conferencia = _carregar_conferencia_estoque(cur, conferencia_id)
        itens = _listar_itens_conferencia_estoque(cur, conferencia_id)
        conn.commit()
    finally:
        cur.close()
        conn.close()

    _remover_xml_nfe_cache(conferencia.get("chave_acesso"))

    return jsonify({
        "ok": True,
        "conferencia": _estoque_conferencia_publica(conferencia),
        "itens": [_estoque_conferencia_item_publico(item) for item in itens],
    })

# =========================================================
# (5) DEVOLUÇÕES (COM FOTOS)
# =========================================================
@app.route("/api/devolucoes/fotos/<path:filename>")
def servir_foto_devolucao(filename):
    return send_from_directory(FOTOS_DIR, filename)

@app.route("/api/devolucoes/<int:id>/fotos", methods=["GET"])
def listar_fotos_devolucao(id):
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT fotos FROM devolucoes WHERE id=%s", (id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    fotos = _json_list_or_empty(row.get("fotos") if row else None)
    urls = [f"/api/devolucoes/fotos/{p}" for p in fotos]
    return jsonify({"id": id, "fotos": urls})

@app.route("/api/devolucoes/<int:id>", methods=["DELETE"])
def deletar_devolucao(id):
    """Remove do banco e também apaga as fotos da devolução."""
    usuario = _usuario_ator_req()
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id, frete_id, veiculo_id, conferente_id FROM devolucoes WHERE id=%s", (id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return jsonify({"erro": "devolucao nao encontrada"}), 404

    cursor.execute("DELETE FROM devolucoes WHERE id=%s", (id,))
    descricao = f"devolucao id={id} frete_id={_as_int(row.get('frete_id'),0)} veiculo_id={_as_int(row.get('veiculo_id'),0)} conferente_id={_as_int(row.get('conferente_id'),0)}"
    _registrar_log_exclusao(cursor, usuario, "devolucoes", id, descricao)
    conn.commit()
    cursor.close()
    conn.close()

    apagou = _safe_remove_devolucao_folder(id)
    return jsonify({"ok": True, "fotos_apagadas": True if apagou else False})

@app.route("/api/devolucoes/<int:id>", methods=["PUT"])
def atualizar_devolucao(id):
    data = request.json or {}
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE devolucoes
    SET frete_id=%s,
        veiculo_id=%s,
        conferente_id=%s,
        c24=%s, obs_c24=%s,
        c48=%s, obs_c48=%s,
        pet2l=%s, obs_pet2l=%s,
        pet600=%s, obs_pet600=%s,
        pet200=%s, obs_pet200=%s,
        agua_com_gas=%s, obs_agua_com_gas=%s,
        agua_sem_gas=%s, obs_agua_sem_gas=%s,
        cx_600=%s, obs_cx_600=%s
    WHERE id=%s
    """, (
        data["frete_id"],
        data["veiculo_id"],
        data["conferente_id"],
        data["c24"], data.get("obs_c24"),
        data["c48"], data.get("obs_c48"),
        data["pet2l"], data.get("obs_pet2l"),
        data["pet600"], data.get("obs_pet600"),
        data["pet200"], data.get("obs_pet200"),
        data.get("agua_com_gas"), data.get("obs_agua_com_gas"),
        data.get("agua_sem_gas"), data.get("obs_agua_sem_gas"),
        data.get("cx_600"), data.get("obs_cx_600"),
        id
    ))

    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/devolucoes", methods=["GET"])
def listar_devolucoes():
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT 
        d.id,
        f.nome AS frete_nome,
        v.nome AS veiculo_nome,
        c.nome AS conferente_nome,

        d.frete_id,
        d.veiculo_id,
        d.conferente_id,

        d.c24, d.c48, d.pet2l, d.pet600, d.pet200,
        d.obs_c24, d.obs_c48, d.obs_pet2l, d.obs_pet600, d.obs_pet200,
        d.agua_com_gas, d.obs_agua_com_gas,
        d.agua_sem_gas, d.obs_agua_sem_gas,
        d.cx_600, d.obs_cx_600,

        d.fotos
    FROM devolucoes d
    LEFT JOIN fretes f ON d.frete_id = f.id
    LEFT JOIN veiculos v ON d.veiculo_id = v.id
    LEFT JOIN conferentes c ON d.conferente_id = c.id
    ORDER BY d.id DESC
    """)

    dados = cursor.fetchall()
    cursor.close()
    conn.close()

    for d in dados:
        fotos = _json_list_or_empty(d.get("fotos"))
        d["fotos"] = fotos
        d["tem_fotos"] = True if fotos else False

    return jsonify(dados)

@app.route("/api/devolucoes", methods=["POST"])
def criar_devolucao():
    is_multipart = (request.content_type or "").startswith("multipart/form-data")

    if is_multipart:
        form = request.form
        files = request.files.getlist("fotos")
        data = {
            "frete_id": form.get("frete_id"),
            "veiculo_id": form.get("veiculo_id"),
            "conferente_id": form.get("conferente_id"),
            "c24": _as_int(form.get("c24"), 0),
            "c48": _as_int(form.get("c48"), 0),
            "pet2l": _as_int(form.get("pet2l"), 0),
            "pet600": _as_int(form.get("pet600"), 0),
            "pet200": _as_int(form.get("pet200"), 0),
            "obs_c24": _as_str(form.get("obs_c24")),
            "obs_c48": _as_str(form.get("obs_c48")),
            "obs_pet2l": _as_str(form.get("obs_pet2l")),
            "obs_pet600": _as_str(form.get("obs_pet600")),
            "obs_pet200": _as_str(form.get("obs_pet200")),
            "agua_com_gas": _as_int(form.get("agua_com_gas"), 0),
            "obs_agua_com_gas": _as_str(form.get("obs_agua_com_gas")),
            "agua_sem_gas": _as_int(form.get("agua_sem_gas"), 0),
            "obs_agua_sem_gas": _as_str(form.get("obs_agua_sem_gas")),
            "cx_600": _as_int(form.get("cx_600"), 0),
            "obs_cx_600": _as_str(form.get("obs_cx_600")),
        }
    else:
        data = request.json or {}
        files = []

    if not data.get("frete_id") or not data.get("conferente_id"):
        return jsonify({"erro": "frete_id e conferente_id são obrigatórios"}), 400

    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO devolucoes
    (frete_id, veiculo_id, conferente_id,
     c24, c48, pet2l, pet600, pet200,
     obs_c24, obs_c48, obs_pet2l, obs_pet600, obs_pet200,
     agua_com_gas, obs_agua_com_gas, agua_sem_gas, obs_agua_sem_gas, cx_600, obs_cx_600,
     fotos)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        data.get("frete_id"),
        data.get("veiculo_id"),
        data.get("conferente_id"),
        data.get("c24"),
        data.get("c48"),
        data.get("pet2l"),
        data.get("pet600"),
        data.get("pet200"),
        data.get("obs_c24"),
        data.get("obs_c48"),
        data.get("obs_pet2l"),
        data.get("obs_pet600"),
        data.get("obs_pet200"),
        data.get("agua_com_gas"),
        data.get("obs_agua_com_gas"),
        data.get("agua_sem_gas"),
        data.get("obs_agua_sem_gas"),
        data.get("cx_600"),
        data.get("obs_cx_600"),
        None
    ))
    devolucao_id = cursor.lastrowid

    fotos_rel = _save_devolucao_files(devolucao_id, files)
    if fotos_rel:
        cursor.execute(
            "UPDATE devolucoes SET fotos=%s WHERE id=%s",
            (json.dumps(fotos_rel), devolucao_id)
        )

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"ok": True, "id": devolucao_id, "fotos": fotos_rel})

# =========================================================
# (6) FRETES
# =========================================================
@app.route("/api/fretes", methods=["POST"])
def criar_frete():
    data = request.json or {}
    usuario = _usuario_ator_req()
    nome = _as_str(data.get("nome"))
    if not nome:
        return jsonify({"erro": "nome do frete e obrigatorio"}), 400
    cidade = _as_str(data.get("cidade"))
    data_carga = _as_date(data.get("data_carga")) or datetime.date.today()
    motorista_id = _as_int(data.get("motorista_id"), 0) or None
    entregador_id = _as_int(data.get("entregador_id"), 0) or motorista_id
    veiculo_id = _as_int(data.get("veiculo_id"), 0) or None
    carga_id = _as_int(data.get("carga_id"), 0) or None
    observacao = _as_str(data.get("observacao"))
    km_atual = _as_int(data.get("km_atual"), 0)
    peso = _as_float(data.get("peso"), 0.0)
    qtd_entregas = _as_int(data.get("qtd_entregas"), 0)

    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        INSERT INTO fretes
            (nome, cidade, data_carga, status, motorista_id, entregador_id, veiculo_id, carga_id, observacao, km_atual, peso, qtd_entregas)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (nome, cidade, data_carga, "liberado", motorista_id, entregador_id, veiculo_id, carga_id, observacao, km_atual, peso, qtd_entregas)
    )
    frete_id = cursor.lastrowid
    if veiculo_id and km_atual > 0:
        cursor.execute(
            """
            UPDATE veiculos
            SET km_atual = CASE
                WHEN km_atual IS NULL OR km_atual < %s THEN %s
                ELSE km_atual
            END
            WHERE id = %s
            """,
            (km_atual, km_atual, veiculo_id)
        )
    frete = _buscar_frete_detalhado(cursor, frete_id)
    _registrar_historico_frete(cursor, frete_id, "criado", usuario, None, frete)
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"ok": True, "id": frete_id, "frete": frete})

@app.route("/api/fretes/<int:id>", methods=["DELETE"])
def deletar_frete(id):
    usuario = _usuario_ator_req()
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    frete = _buscar_frete_detalhado(cursor, id)
    if not frete:
        cursor.close()
        conn.close()
        return jsonify({"erro": "frete nao encontrado"}), 404

    cursor.execute("DELETE FROM fretes_historico WHERE frete_id=%s", (id,))
    cursor.execute("DELETE FROM fretes WHERE id=%s", (id,))
    descricao = f"frete id={id} nome={_as_str(frete.get('nome'))} status={_as_str(frete.get('status'))}"
    _registrar_log_exclusao(cursor, usuario, "fretes", id, descricao)
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/fretes/<int:id>", methods=["PUT"])
def atualizar_frete(id):
    data = request.json or {}
    usuario = _usuario_ator_req()
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    antes = _buscar_frete_detalhado(cursor, id)
    if not antes:
        cursor.close()
        conn.close()
        return jsonify({"erro": "frete nao encontrado"}), 404

    nome = _as_str(data.get("nome")) if ("nome" in data and data.get("nome") is not None) else _as_str(antes.get("nome"))
    cidade = _as_str(data.get("cidade")) if ("cidade" in data and data.get("cidade") is not None) else _as_str(antes.get("cidade"))
    data_carga = (
        _as_date(data.get("data_carga"))
        if "data_carga" in data else _as_date(antes.get("data_carga"))
    )
    status = _as_str(data.get("status")) if ("status" in data and data.get("status") is not None) else _as_str(antes.get("status"))
    motorista_id = (
        _as_int(data.get("motorista_id"), 0) or None
        if "motorista_id" in data else (_as_int(antes.get("motorista_id"), 0) or None)
    )
    entregador_id = (
        _as_int(data.get("entregador_id"), 0) or None
        if "entregador_id" in data else (_as_int(antes.get("entregador_id"), 0) or None)
    )
    if entregador_id is None and motorista_id:
        entregador_id = motorista_id
    veiculo_id = (
        _as_int(data.get("veiculo_id"), 0) or None
        if "veiculo_id" in data else (_as_int(antes.get("veiculo_id"), 0) or None)
    )
    carga_id = (
        _as_int(data.get("carga_id"), 0) or None
        if "carga_id" in data else (_as_int(antes.get("carga_id"), 0) or None)
    )
    observacao = _as_str(data.get("observacao")) if ("observacao" in data and data.get("observacao") is not None) else _as_str(antes.get("observacao"))
    km_atual = _as_int(data.get("km_atual"), 0) if ("km_atual" in data and data.get("km_atual") is not None) else _as_int(antes.get("km_atual"), 0)
    peso = _as_float(data.get("peso"), 0.0) if ("peso" in data and data.get("peso") is not None) else _as_float(antes.get("peso"), 0.0)
    qtd_entregas = _as_int(data.get("qtd_entregas"), 0) if ("qtd_entregas" in data and data.get("qtd_entregas") is not None) else _as_int(antes.get("qtd_entregas"), 0)

    if not nome:
        cursor.close()
        conn.close()
        return jsonify({"erro": "nome do frete e obrigatorio"}), 400

    comparacao_antes = {
        "nome": _as_str(antes.get("nome")),
        "cidade": _as_str(antes.get("cidade")),
        "data_carga": _as_str(antes.get("data_carga")),
        "status": _as_str(antes.get("status")),
        "motorista_id": _as_int(antes.get("motorista_id"), 0) or None,
        "entregador_id": _as_int(antes.get("entregador_id"), 0) or None,
        "veiculo_id": _as_int(antes.get("veiculo_id"), 0) or None,
        "carga_id": _as_int(antes.get("carga_id"), 0) or None,
        "observacao": _as_str(antes.get("observacao")),
        "km_atual": _as_int(antes.get("km_atual"), 0),
        "peso": _as_float(antes.get("peso"), 0.0),
        "qtd_entregas": _as_int(antes.get("qtd_entregas"), 0),
    }
    comparacao_depois = {
        "nome": nome,
        "cidade": cidade,
        "data_carga": _fmt_date(data_carga),
        "status": status,
        "motorista_id": motorista_id,
        "entregador_id": entregador_id,
        "veiculo_id": veiculo_id,
        "carga_id": carga_id,
        "observacao": observacao,
        "km_atual": km_atual,
        "peso": peso,
        "qtd_entregas": qtd_entregas,
    }
    if comparacao_antes == comparacao_depois:
        cursor.close()
        conn.close()
        return jsonify({"ok": True, "frete": antes})

    cursor.execute("""
        UPDATE fretes
        SET
          nome = %s,
          cidade = %s,
          data_carga = %s,
          status = %s,
          motorista_id = %s,
          entregador_id = %s,
          veiculo_id = %s,
          carga_id = %s,
          observacao = %s,
          km_atual = %s,
          peso = %s,
          qtd_entregas = %s,
          finalizado_em = CASE
            WHEN %s = 'retornando' AND status <> 'retornando' THEN NOW()
            WHEN status = 'retornando' AND %s <> 'retornando' THEN NULL
            ELSE finalizado_em
          END
        WHERE id = %s
    """, (
        nome,
        cidade,
        data_carga,
        status,
        motorista_id,
        entregador_id,
        veiculo_id,
        carga_id,
        observacao,
        km_atual,
        peso,
        qtd_entregas,
        status,
        status,
        id
    ))

    veiculo_id_num = _as_int(veiculo_id, 0)
    km_atual_num = _as_int(km_atual, 0)
    if veiculo_id_num > 0 and km_atual_num > 0:
        cursor.execute(
            """
            UPDATE veiculos
            SET km_atual = CASE
                WHEN km_atual IS NULL OR km_atual < %s THEN %s
                ELSE km_atual
            END
            WHERE id = %s
            """,
            (km_atual_num, km_atual_num, veiculo_id_num)
        )

    depois = _buscar_frete_detalhado(cursor, id)
    _registrar_historico_frete(cursor, id, "atualizado", usuario, antes, depois)
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"ok": True, "frete": depois})

@app.route("/api/fretes", methods=["GET"])
def listar_fretes():
    _limpar_fretes_finalizados_expirados()
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(FRETE_SELECT_SQL + " ORDER BY f.id DESC")
    dados = [_serialize_frete_row(row) for row in (cursor.fetchall() or [])]
    cursor.close()
    conn.close()
    return jsonify(dados)

# =========================================================
# (7) CADASTROS GENÉRICOS
# =========================================================
@app.route("/api/usuarios", methods=["GET"])
def listar_usuarios():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            id,
            nome,
            login,
            ativo,
            sip_habilitado,
            sip_usuario,
            sip_ramal,
            codbar_modo,
            data_cadastro
        FROM usuarios
        ORDER BY nome ASC, id ASC
    """)
    rows = cur.fetchall() or []
    cur.close()
    conn.close()
    return jsonify([_usuario_publico_dict(r) for r in rows])

@app.route("/api/usuarios", methods=["POST"])
def criar_usuario():
    data = request.json or {}
    nome = _as_str(data.get("nome"))
    login = _as_str(data.get("login"))
    senha = _as_str(data.get("senha"))
    sip_habilitado = 1 if _as_bool(data.get("sip_habilitado"), False) else 0
    sip_usuario = _as_str(data.get("sip_usuario"))
    sip_senha = _as_str(data.get("sip_senha"))
    sip_ramal = _as_str(data.get("sip_ramal"))
    codbar_modo = _normalizar_codbar_modo(data.get("codbar_modo"))

    if not nome:
        return jsonify({"erro": "nome e obrigatorio"}), 400
    if not login:
        return jsonify({"erro": "login e obrigatorio"}), 400
    if not senha:
        return jsonify({"erro": "senha e obrigatoria"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM usuarios WHERE login=%s LIMIT 1", (login,))
        if cur.fetchone():
            return jsonify({"erro": "login ja existe"}), 409

        cur.execute(
            """
            INSERT INTO usuarios (
                nome, login, senha, ativo,
                sip_habilitado, sip_usuario, sip_senha, sip_ramal, codbar_modo
            ) VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s)
            """,
            (nome, login, generate_password_hash(senha), sip_habilitado, sip_usuario, sip_senha, sip_ramal, codbar_modo)
        )
        user_id = cur.lastrowid
        conn.commit()
        try:
            _sincronizar_usuarios_sip(conn, senha_plana_por_id={user_id: sip_senha or senha}, apenas_ids=[user_id])
            conn.commit()
        except Exception as exc:
            conn.rollback()
            print(f"WARN sip sync create user {user_id}:", exc)
    finally:
        cur.close()
        conn.close()

    _sincronizar_usuario_freepbx_best_effort(user_id)
    return jsonify({"ok": True, "id": user_id})

@app.route("/api/login", methods=["POST"])
def login_usuario():
    data = request.json or {}
    login = _as_str(data.get("login"))
    senha = _as_str(data.get("senha"))
    if not login or not senha:
        return jsonify({"erro": "login e senha sao obrigatorios"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT id, nome, login, senha, ativo, sip_usuario, sip_senha, sip_ramal, codbar_modo
        FROM usuarios
        WHERE login=%s
        LIMIT 1
        """,
        (login,)
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({"erro": "credenciais invalidas"}), 401

    senha_ok = False
    senha_db = str(row.get("senha") or "")
    # Aceita hash atual; fallback temporario para texto puro legado.
    try:
        senha_ok = check_password_hash(senha_db, senha)
    except Exception:
        senha_ok = False
    legacy_plain = (not senha_ok and senha_db == senha)
    if legacy_plain:
        senha_ok = True
        try:
            cur2 = conn.cursor()
            cur2.execute("UPDATE usuarios SET senha=%s WHERE id=%s", (generate_password_hash(senha), row.get("id")))
            conn.commit()
            cur2.close()
        except Exception:
            pass

    if senha_ok:
        try:
            _sincronizar_usuarios_sip(conn, senha_plana_por_id={_as_int(row.get("id"), 0): senha}, apenas_ids=[row.get("id")])
            conn.commit()
        except Exception:
            pass

    cur.close()
    conn.close()

    if not senha_ok:
        return jsonify({"erro": "credenciais invalidas"}), 401
    if _as_int(row.get("ativo"), 1) != 1:
        return jsonify({"erro": "usuario inativo"}), 403

    _sincronizar_usuario_freepbx_best_effort(row.get("id"))

    return jsonify({
        "ok": True,
        "usuario": {
            "id": _as_int(row.get("id"), 0),
            "nome": _as_str(row.get("nome")),
            "login": _as_str(row.get("login")),
            "codbar_modo": _normalizar_codbar_modo(row.get("codbar_modo")),
        }
    })

@app.route("/api/usuarios/<int:user_id>", methods=["GET", "PUT"])
def atualizar_usuario(user_id):
    if request.method == "GET":
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT
                id,
                nome,
                login,
                ativo,
                sip_habilitado,
                sip_usuario,
                sip_ramal,
                codbar_modo,
                data_cadastro
            FROM usuarios
            WHERE id=%s
            LIMIT 1
        """, (user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"erro": "usuario nao encontrado"}), 404
        return jsonify(_usuario_publico_dict(row))

    data = request.json or {}
    nome = _as_str(data.get("nome"))
    login = _as_str(data.get("login"))
    senha = _as_str(data.get("senha"))
    sip_habilitado = 1 if _as_bool(data.get("sip_habilitado"), False) else 0
    sip_usuario = _as_str(data.get("sip_usuario"))
    sip_senha = _as_str(data.get("sip_senha"))
    sip_ramal = _as_str(data.get("sip_ramal"))
    codbar_modo = _normalizar_codbar_modo(data.get("codbar_modo"))

    if not nome:
        return jsonify({"erro": "nome e obrigatorio"}), 400
    if not login:
        return jsonify({"erro": "login e obrigatorio"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    sip_ramal_atual = ""
    try:
        cur.execute("SELECT id, sip_senha, sip_ramal FROM usuarios WHERE id=%s LIMIT 1", (user_id,))
        row_existente = cur.fetchone()
        if not row_existente:
            return jsonify({"erro": "usuario nao encontrado"}), 404
        sip_ramal_anterior = _sip_ramal_interno(row_existente.get("sip_ramal"))

        cur.execute("SELECT id FROM usuarios WHERE login=%s AND id<>%s LIMIT 1", (login, user_id))
        if cur.fetchone():
            return jsonify({"erro": "login ja existe"}), 409

        limpar_sip_senha = _as_bool(data.get("limpar_sip_senha"), False)
        sip_senha_final = sip_senha
        if not sip_senha:
            if limpar_sip_senha:
                sip_senha_final = ""
            elif senha:
                sip_senha_final = senha
            else:
                sip_senha_final = _as_str(row_existente.get("sip_senha"))

        if senha:
            cur.execute(
                """
                UPDATE usuarios
                SET nome=%s, login=%s, senha=%s, sip_habilitado=%s, sip_usuario=%s, sip_senha=%s, sip_ramal=%s, codbar_modo=%s
                WHERE id=%s
                """,
                (nome, login, generate_password_hash(senha), sip_habilitado, sip_usuario, sip_senha_final, sip_ramal, codbar_modo, user_id)
            )
        else:
            cur.execute(
                """
                UPDATE usuarios
                SET nome=%s, login=%s, sip_habilitado=%s, sip_usuario=%s, sip_senha=%s, sip_ramal=%s, codbar_modo=%s
                WHERE id=%s
                """,
                (nome, login, sip_habilitado, sip_usuario, sip_senha_final, sip_ramal, codbar_modo, user_id)
            )
        cur.execute("SELECT sip_ramal FROM usuarios WHERE id=%s LIMIT 1", (user_id,))
        row_atualizada = cur.fetchone() or {}
        sip_ramal_atual = _sip_ramal_interno(row_atualizada.get("sip_ramal"))
        conn.commit()
        try:
            _sincronizar_usuarios_sip(conn, senha_plana_por_id={user_id: sip_senha_final or senha}, apenas_ids=[user_id])
            conn.commit()
        except Exception as exc:
            conn.rollback()
            print(f"WARN sip sync update user {user_id}:", exc)
    finally:
        cur.close()
        conn.close()

    remocoes = [sip_ramal_anterior] if sip_ramal_anterior and sip_ramal_anterior != sip_ramal_atual else []
    _sincronizar_usuario_freepbx_best_effort(user_id, remove_extensions=remocoes)
    return jsonify({"ok": True})

@app.route("/api/usuarios/<int:user_id>", methods=["DELETE"])
def deletar_usuario(user_id):
    usuario = _usuario_ator_req()
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome, login, sip_ramal FROM usuarios WHERE id=%s LIMIT 1", (user_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"erro": "usuario nao encontrado"}), 404
        sip_ramal_removido = _sip_ramal_interno(row.get("sip_ramal"))

        cur.execute("DELETE FROM usuarios WHERE id=%s", (user_id,))
        descricao = f"usuario id={user_id} nome={_as_str(row.get('nome'))} login={_as_str(row.get('login'))}"
        _registrar_log_exclusao(cur, usuario, "usuarios", user_id, descricao)
        conn.commit()
    finally:
        cur.close()
        conn.close()
    if sip_ramal_removido:
        _sincronizar_usuario_freepbx_best_effort(user_id, remove_extensions=[sip_ramal_removido])
    return jsonify({"ok": True})

@app.route("/api/chat/conversa", methods=["GET"])
def chat_conversa():
    usuario_id = _as_int(request.args.get("usuario_id"), 0)
    contato_id = _as_int(request.args.get("contato_id"), 0)
    limite = _as_int(request.args.get("limit"), 250)
    limite = max(1, min(limite, 500))

    if usuario_id <= 0 or contato_id <= 0:
        return jsonify({"erro": "usuario_id e contato_id sao obrigatorios"}), 400
    if usuario_id == contato_id:
        return jsonify([])

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            m.id,
            m.remetente_id,
            m.destinatario_id,
            m.mensagem,
            m.anexo_nome,
            m.anexo_path,
            m.anexo_mime,
            m.anexo_tamanho,
            m.lida,
            m.data_envio,
            ur.nome AS remetente_nome,
            ud.nome AS destinatario_nome
        FROM chat_mensagens m
        LEFT JOIN usuarios ur ON ur.id = m.remetente_id
        LEFT JOIN usuarios ud ON ud.id = m.destinatario_id
        WHERE
            (m.remetente_id = %s AND m.destinatario_id = %s)
            OR
            (m.remetente_id = %s AND m.destinatario_id = %s)
        ORDER BY m.id DESC
        LIMIT %s
    """, (usuario_id, contato_id, contato_id, usuario_id, limite))
    rows = cur.fetchall() or []

    cur.execute("""
        UPDATE chat_mensagens
        SET lida = 1
        WHERE remetente_id = %s AND destinatario_id = %s AND lida = 0
    """, (contato_id, usuario_id))
    conn.commit()

    cur.close()
    conn.close()

    rows.reverse()
    out = []
    for r in rows:
        anexo_path = _as_str(r.get("anexo_path"))
        anexo_nome = _as_str(r.get("anexo_nome"))
        anexo_mime = _as_str(r.get("anexo_mime"))
        tem_anexo = bool(anexo_path)
        anexo_url = f"/api/chat/mensagens/{_as_int(r.get('id'), 0)}/anexo?usuario_id={usuario_id}" if tem_anexo else ""
        out.append({
            "id": _as_int(r.get("id"), 0),
            "remetente_id": _as_int(r.get("remetente_id"), 0),
            "destinatario_id": _as_int(r.get("destinatario_id"), 0),
            "remetente_nome": _as_str(r.get("remetente_nome")),
            "destinatario_nome": _as_str(r.get("destinatario_nome")),
            "mensagem": _as_str(r.get("mensagem")),
            "tem_anexo": tem_anexo,
            "anexo_nome": anexo_nome,
            "anexo_mime": anexo_mime,
            "anexo_tamanho": _as_int(r.get("anexo_tamanho"), 0),
            "anexo_eh_imagem": _chat_attachment_is_image(anexo_mime, anexo_nome),
            "anexo_url": anexo_url,
            "anexo_inline_url": f"{anexo_url}&inline=1" if anexo_url else "",
            "lida": bool(_as_int(r.get("lida"), 0)),
            "data_envio": _fmt_dt(r.get("data_envio")),
        })
    return jsonify(out)

@app.route("/api/chat/mensagens/<int:mensagem_id>/anexo", methods=["GET"])
def chat_download_anexo(mensagem_id):
    usuario_id = _as_int(request.args.get("usuario_id"), 0)
    if mensagem_id <= 0 or usuario_id <= 0:
        return jsonify({"erro": "mensagem_id e usuario_id sao obrigatorios"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT id, remetente_id, destinatario_id, anexo_nome, anexo_path, anexo_mime
        FROM chat_mensagens
        WHERE id = %s
        LIMIT 1
    """, (mensagem_id,))
    row = cur.fetchone() or {}
    cur.close()
    conn.close()

    if not row:
        return jsonify({"erro": "mensagem nao encontrada"}), 404

    remetente_id = _as_int(row.get("remetente_id"), 0)
    destinatario_id = _as_int(row.get("destinatario_id"), 0)
    if usuario_id not in (remetente_id, destinatario_id):
        return jsonify({"erro": "acesso negado"}), 403

    caminho_abs = _chat_attachment_abs(row.get("anexo_path"))
    if not caminho_abs or not os.path.isfile(caminho_abs):
        return jsonify({"erro": "anexo nao encontrado"}), 404

    inline = _as_bool(request.args.get("inline"), False)
    nome = _as_str(row.get("anexo_nome")) or os.path.basename(caminho_abs)
    mime = _as_str(row.get("anexo_mime")) or (mimetypes.guess_type(nome)[0] or "application/octet-stream")
    return send_file(caminho_abs, as_attachment=not inline, download_name=nome, mimetype=mime, conditional=True, max_age=0)

@app.route("/api/chat/mensagens", methods=["POST"])
def chat_enviar_mensagem():
    is_json = request.is_json
    data = (request.json or {}) if is_json else request.form
    remetente_id = _as_int(data.get("remetente_id"), 0)
    destinatario_id = _as_int(data.get("destinatario_id"), 0)
    mensagem = _as_str(data.get("mensagem")).strip()
    anexo = request.files.get("anexo") if not is_json else None

    if remetente_id <= 0 or destinatario_id <= 0:
        return jsonify({"erro": "remetente_id e destinatario_id sao obrigatorios"}), 400
    if remetente_id == destinatario_id:
        return jsonify({"erro": "nao e permitido enviar para o mesmo usuario"}), 400
    if not mensagem and (not anexo or not getattr(anexo, "filename", "")):
        return jsonify({"erro": "mensagem ou anexo obrigatorio"}), 400

    anexo_info = None

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM usuarios WHERE id=%s LIMIT 1", (remetente_id,))
        if not cur.fetchone():
            return jsonify({"erro": "remetente nao encontrado"}), 404

        cur.execute("SELECT id FROM usuarios WHERE id=%s LIMIT 1", (destinatario_id,))
        if not cur.fetchone():
            return jsonify({"erro": "destinatario nao encontrado"}), 404

        if anexo and getattr(anexo, "filename", ""):
            anexo_info = _save_chat_attachment(anexo)
            if not anexo_info:
                return jsonify({"erro": "falha ao processar anexo"}), 400

        cur.execute(
            """
            INSERT INTO chat_mensagens (
                remetente_id, destinatario_id, mensagem,
                anexo_nome, anexo_path, anexo_mime, anexo_tamanho,
                lida, data_envio
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, NOW())
            """,
            (
                remetente_id,
                destinatario_id,
                mensagem,
                _as_str(anexo_info.get("nome") if anexo_info else ""),
                _as_str(anexo_info.get("path") if anexo_info else ""),
                _as_str(anexo_info.get("mime") if anexo_info else ""),
                _as_int(anexo_info.get("tamanho") if anexo_info else 0, 0),
            )
        )
        msg_id = cur.lastrowid
        conn.commit()
    except Exception:
        if anexo_info:
            try:
                os.remove(anexo_info.get("abs_path"))
            except Exception:
                pass
        raise
    finally:
        cur.close()
        conn.close()

    return jsonify({"ok": True, "id": msg_id})

@app.route("/api/chat/marcar_lidas", methods=["PUT"])
def chat_marcar_lidas():
    data = request.json or {}
    usuario_id = _as_int(data.get("usuario_id"), 0)
    contato_id = _as_int(data.get("contato_id"), 0)
    if usuario_id <= 0 or contato_id <= 0:
        return jsonify({"erro": "usuario_id e contato_id sao obrigatorios"}), 400
    if usuario_id == contato_id:
        return jsonify({"ok": True, "marcadas": 0})

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE chat_mensagens
            SET lida = 1
            WHERE remetente_id = %s
              AND destinatario_id = %s
              AND lida = 0
        """, (contato_id, usuario_id))
        marcadas = int(cur.rowcount or 0)
        cur.execute(
            "SELECT COUNT(*) AS total FROM chat_mensagens WHERE destinatario_id = %s AND lida = 0",
            (usuario_id,)
        )
        row_total = cur.fetchone() or (0,)
        try:
            total_restante = int(row_total[0] or 0)
        except Exception:
            total_restante = 0
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return jsonify({"ok": True, "marcadas": marcadas, "total_mensagens_nao_lidas": total_restante})

@app.route("/api/chat/unread", methods=["GET"])
def chat_unread():
    usuario_id = _as_int(request.args.get("usuario_id"), 0)
    if usuario_id <= 0:
        return jsonify({"erro": "usuario_id obrigatorio"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) AS total FROM chat_mensagens WHERE destinatario_id = %s AND lida = 0", (usuario_id,))
    total_row = cur.fetchone() or {}
    total_mensagens = _as_int(total_row.get("total"), 0)

    cur.execute("""
        SELECT
            m.remetente_id,
            u.nome AS remetente_nome,
            COUNT(*) AS total
        FROM chat_mensagens m
        LEFT JOIN usuarios u ON u.id = m.remetente_id
        WHERE m.destinatario_id = %s AND m.lida = 0
        GROUP BY m.remetente_id, u.nome
        ORDER BY total DESC, m.remetente_id ASC
    """, (usuario_id,))
    rows = cur.fetchall() or []
    cur.close()
    conn.close()

    por_contato = []
    for r in rows:
        qtd = _as_int(r.get("total"), 0)
        por_contato.append({
            "remetente_id": _as_int(r.get("remetente_id"), 0),
            "remetente_nome": _as_str(r.get("remetente_nome")),
            "total": qtd,
        })
    return jsonify({
        "total": total_mensagens,  # compat
        "total_mensagens_nao_lidas": total_mensagens,
        "total_conversas_com_nao_lidas": len(por_contato),
        "por_contato": por_contato
    })

@app.route("/api/comissao/lancamentos", methods=["GET"])
def listar_comissao_lancamentos():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            id, cod_vendedor, motorista, entregador, rota, usina,
            data_faturamento, data_saida, data_chegada,
            v_gf, d_gf, icms_gf, v_pet, d_pet, icms_pet, v_agua, d_agua,
            gf_600, gf_200, gf_300, dev_gf, pet_2l, pet_600, dev_pet,
            agua_vol, total_pedidos, acucar_qtd, t_acucar,
            pct_vend_gf, pct_vend_pet, pct_vend_agua,
            pct_ent_gf, pct_ent_pet, pct_ent_agua, taxa_ent_acucar,
            criado_em
        FROM comissao_lancamentos
        ORDER BY id DESC
    """)
    rows = cur.fetchall() or []
    cur.close()
    conn.close()

    out = []
    for r in rows:
        calc = _calc_comissao_lancamento(r)
        out.append({
            "id": _as_int(r.get("id"), 0),
            "cod_vendedor": _as_int(r.get("cod_vendedor"), 0),
            "motorista": _as_str(r.get("motorista")),
            "entregador": _as_str(r.get("entregador")),
            "rota": _as_str(r.get("rota")),
            "usina": _as_str(r.get("usina")),
            "data_faturamento": _fmt_dt(r.get("data_faturamento")),
            "data_saida": _fmt_dt(r.get("data_saida")),
            "data_chegada": _fmt_dt(r.get("data_chegada")),
            "criado_em": _fmt_dt(r.get("criado_em")),
            **calc,
        })
    return jsonify(out)

@app.route("/api/comissao/lancamentos", methods=["POST"])
def criar_comissao_lancamento():
    data = request.json or {}
    motorista = _as_str(data.get("motorista"))
    entregador = _as_str(data.get("entregador"))
    rota = _as_str(data.get("rota"))
    if not motorista or not entregador or not rota:
        return jsonify({"erro": "motorista, entregador e rota sao obrigatorios"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO comissao_lancamentos (
            cod_vendedor, motorista, entregador, rota, usina,
            data_faturamento, data_saida, data_chegada,
            v_gf, d_gf, icms_gf, v_pet, d_pet, icms_pet, v_agua, d_agua,
            gf_600, gf_200, gf_300, dev_gf, pet_2l, pet_600, dev_pet,
            agua_vol, total_pedidos, acucar_qtd, t_acucar,
            pct_vend_gf, pct_vend_pet, pct_vend_agua,
            pct_ent_gf, pct_ent_pet, pct_ent_agua, taxa_ent_acucar
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s
        )
    """, (
        _as_int(data.get("cod_vendedor"), 0), motorista, entregador, rota, _as_str(data.get("usina")),
        _as_date(data.get("data_faturamento")), _as_date(data.get("data_saida")), _as_date(data.get("data_chegada")),
        _as_float(data.get("v_gf"), 0.0), _as_float(data.get("d_gf"), 0.0), _as_float(data.get("icms_gf"), 0.0),
        _as_float(data.get("v_pet"), 0.0), _as_float(data.get("d_pet"), 0.0), _as_float(data.get("icms_pet"), 0.0),
        _as_float(data.get("v_agua"), 0.0), _as_float(data.get("d_agua"), 0.0),
        _as_float(data.get("gf_600"), 0.0), _as_float(data.get("gf_200"), 0.0), _as_float(data.get("gf_300"), 0.0),
        _as_float(data.get("dev_gf"), 0.0), _as_float(data.get("pet_2l"), 0.0), _as_float(data.get("pet_600"), 0.0),
        _as_float(data.get("dev_pet"), 0.0), _as_float(data.get("agua_vol"), 0.0), _as_float(data.get("total_pedidos"), 0.0),
        _as_float(data.get("acucar_qtd"), 0.0), _as_float(data.get("t_acucar"), 0.0),
        _as_float(data.get("pct_vend_gf"), 0.01), _as_float(data.get("pct_vend_pet"), 0.01), _as_float(data.get("pct_vend_agua"), 0.03),
        _as_float(data.get("pct_ent_gf"), 0.08), _as_float(data.get("pct_ent_pet"), 0.06), _as_float(data.get("pct_ent_agua"), 0.06),
        _as_float(data.get("taxa_ent_acucar"), 0.0),
    ))
    novo_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True, "id": _as_int(novo_id, 0)})

@app.route("/api/comissao/lancamentos/<int:item_id>", methods=["DELETE"])
def deletar_comissao_lancamento(item_id):
    usuario = _usuario_ator_req()
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, cod_vendedor, motorista, entregador, rota FROM comissao_lancamentos WHERE id=%s", (item_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({"erro": "lancamento nao encontrado"}), 404

    cur.execute("DELETE FROM comissao_lancamentos WHERE id=%s", (item_id,))
    descricao = f"comissao id={item_id} cod={_as_int(row.get('cod_vendedor'),0)} motorista={_as_str(row.get('motorista'))} entregador={_as_str(row.get('entregador'))} rota={_as_str(row.get('rota'))}"
    _registrar_log_exclusao(cur, usuario, "comissao_lancamentos", item_id, descricao)
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/comissao/cadastros", methods=["GET"])
def listar_comissao_cadastros():
    funcao = _as_str(request.args.get("funcao")).lower()
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    sql = """
        SELECT id, codigo, nome, funcao, pct_gf, pct_pet, pct_agua, ativo, criado_em
        FROM comissao_cadastros
    """
    params = []
    if funcao:
        sql += " WHERE LOWER(funcao) = %s"
        params.append(funcao)
    sql += " ORDER BY funcao ASC, codigo ASC, nome ASC"
    cur.execute(sql, tuple(params))
    rows = cur.fetchall() or []
    cur.close()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": _as_int(r.get("id"), 0),
            "codigo": _as_int(r.get("codigo"), 0),
            "nome": _as_str(r.get("nome")),
            "funcao": _as_str(r.get("funcao")).lower(),
            "pct_gf": _as_float(r.get("pct_gf"), 0.0),
            "pct_pet": _as_float(r.get("pct_pet"), 0.0),
            "pct_agua": _as_float(r.get("pct_agua"), 0.0),
            "ativo": bool(_as_int(r.get("ativo"), 1)),
            "criado_em": _fmt_dt(r.get("criado_em")),
        })
    return jsonify(out)

@app.route("/api/comissao/cadastros", methods=["POST"])
def criar_comissao_cadastro():
    data = request.json or {}
    nome = _as_str(data.get("nome"))
    funcao = _as_str(data.get("funcao")).lower()
    if not nome or funcao not in ["vendedor", "entregador", "acucar", "usina"]:
        return jsonify({"erro": "nome e funcao validos sao obrigatorios"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO comissao_cadastros (codigo, nome, funcao, pct_gf, pct_pet, pct_agua, ativo)
        VALUES (%s, %s, %s, %s, %s, %s, 1)
    """, (
        _as_int(data.get("codigo"), 0),
        nome,
        funcao,
        _as_float(data.get("pct_gf"), 0.0),
        _as_float(data.get("pct_pet"), 0.0),
        _as_float(data.get("pct_agua"), 0.0),
    ))
    novo_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True, "id": _as_int(novo_id, 0)})

@app.route("/api/comissao/cadastros/<int:item_id>", methods=["DELETE"])
def deletar_comissao_cadastro(item_id):
    usuario = _usuario_ator_req()
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, codigo, nome, funcao FROM comissao_cadastros WHERE id=%s", (item_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({"erro": "cadastro nao encontrado"}), 404
    cur.execute("DELETE FROM comissao_cadastros WHERE id=%s", (item_id,))
    descricao = f"comissao_cadastro id={item_id} codigo={_as_int(row.get('codigo'),0)} nome={_as_str(row.get('nome'))} funcao={_as_str(row.get('funcao'))}"
    _registrar_log_exclusao(cur, usuario, "comissao_cadastros", item_id, descricao)
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/comissao/cidades", methods=["GET"])
def listar_comissao_cidades():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, rota, criado_em FROM comissao_cidades ORDER BY rota ASC")
    rows = cur.fetchall() or []
    cur.close()
    conn.close()
    return jsonify([{
        "id": _as_int(r.get("id"), 0),
        "rota": _as_str(r.get("rota")),
        "criado_em": _fmt_dt(r.get("criado_em")),
    } for r in rows])

@app.route("/api/comissao/cidades", methods=["POST"])
def criar_comissao_cidade():
    data = request.json or {}
    rota = _as_str(data.get("rota"))
    if not rota:
        return jsonify({"erro": "rota obrigatoria"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO comissao_cidades (rota) VALUES (%s)", (rota,))
    novo_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True, "id": _as_int(novo_id, 0)})

@app.route("/api/comissao/cidades/<int:item_id>", methods=["DELETE"])
def deletar_comissao_cidade(item_id):
    usuario = _usuario_ator_req()
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, rota FROM comissao_cidades WHERE id=%s", (item_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({"erro": "rota nao encontrada"}), 404
    cur.execute("DELETE FROM comissao_cidades WHERE id=%s", (item_id,))
    descricao = f"comissao_cidade id={item_id} rota={_as_str(row.get('rota'))}"
    _registrar_log_exclusao(cur, usuario, "comissao_cidades", item_id, descricao)
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})

def _coletar_relatorios_comissao(filtro_cod=0, filtro_entregador=""):
    filtro_cod = _as_int(filtro_cod, 0)
    filtro_entregador = _as_str(filtro_entregador).upper()
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            id, cod_vendedor, motorista, entregador, rota, usina,
            v_gf, d_gf, icms_gf, v_pet, d_pet, icms_pet, v_agua, d_agua,
            gf_600, gf_200, gf_300, dev_gf, pet_2l, pet_600, dev_pet,
            agua_vol, total_pedidos, acucar_qtd, t_acucar,
            pct_vend_gf, pct_vend_pet, pct_vend_agua,
            pct_ent_gf, pct_ent_pet, pct_ent_agua, taxa_ent_acucar
        FROM comissao_lancamentos
    """)
    lancamentos = cur.fetchall() or []

    cur.execute("""
        SELECT codigo, nome, funcao, pct_gf, pct_pet, pct_agua
        FROM comissao_cadastros
        WHERE ativo = 1
    """)
    cad_rows = cur.fetchall() or []
    cur.close()
    conn.close()

    vend_cad = {}
    ent_cad = {}
    for c in cad_rows:
        f = _as_str(c.get("funcao")).lower()
        if f == "vendedor":
            vend_cad[_as_int(c.get("codigo"), 0)] = c
        elif f == "entregador":
            ent_cad[_as_str(c.get("nome")).upper()] = c

    total_vendedores = {}
    total_entregadores = {}
    total_refugo = {}
    total_acucar = {}
    resumo = {
        "total_lancamentos": 0,
        "base_vendedor_total": 0.0,
        "comissao_vendedor_total": 0.0,
        "comissao_entregador_total": 0.0,
    }

    for r in lancamentos:
        cod = _as_int(r.get("cod_vendedor"), 0)
        ent_nome = _as_str(r.get("entregador"))
        if filtro_cod > 0 and cod != filtro_cod:
            continue
        if filtro_entregador and _as_str(ent_nome).upper() != filtro_entregador:
            continue

        calc = _calc_comissao_lancamento(r)
        resumo["total_lancamentos"] += 1
        resumo["base_vendedor_total"] += calc["base_vendedor_total"]

        cad_v = vend_cad.get(cod)
        pct_v_gf = _as_float(cad_v.get("pct_gf"), _as_float(r.get("pct_vend_gf"), 0.01)) if cad_v else _as_float(r.get("pct_vend_gf"), 0.01)
        pct_v_pet = _as_float(cad_v.get("pct_pet"), _as_float(r.get("pct_vend_pet"), 0.01)) if cad_v else _as_float(r.get("pct_vend_pet"), 0.01)
        pct_v_agua = _as_float(cad_v.get("pct_agua"), _as_float(r.get("pct_vend_agua"), 0.03)) if cad_v else _as_float(r.get("pct_vend_agua"), 0.03)
        com_v = (calc["base_gf"] * pct_v_gf) + (calc["base_pet"] * pct_v_pet) + (calc["base_agua"] * pct_v_agua)
        resumo["comissao_vendedor_total"] += com_v

        key_v = cod
        if key_v not in total_vendedores:
            total_vendedores[key_v] = {
                "codigo": cod,
                "nome": _as_str(cad_v.get("nome")) if cad_v else "",
                "base_total": 0.0,
                "comissao_total": 0.0,
            }
        total_vendedores[key_v]["base_total"] += calc["base_vendedor_total"]
        total_vendedores[key_v]["comissao_total"] += com_v

        cad_e = ent_cad.get(_as_str(ent_nome).upper())
        pct_e_gf = _as_float(cad_e.get("pct_gf"), _as_float(r.get("pct_ent_gf"), 0.08)) if cad_e else _as_float(r.get("pct_ent_gf"), 0.08)
        pct_e_pet = _as_float(cad_e.get("pct_pet"), _as_float(r.get("pct_ent_pet"), 0.06)) if cad_e else _as_float(r.get("pct_ent_pet"), 0.06)
        pct_e_agua = _as_float(cad_e.get("pct_agua"), _as_float(r.get("pct_ent_agua"), 0.06)) if cad_e else _as_float(r.get("pct_ent_agua"), 0.06)
        taxa_acucar = _as_float(r.get("taxa_ent_acucar"), 0.0)
        if taxa_acucar <= 0:
            taxa_acucar = _as_float(r.get("t_acucar"), 0.0)
        com_e = (calc["base_ent_gf"] * pct_e_gf) + (calc["base_ent_pet"] * pct_e_pet) + (calc["base_ent_agua"] * pct_e_agua) + (calc["base_ent_acucar"] * taxa_acucar)
        resumo["comissao_entregador_total"] += com_e

        key_e = _as_str(ent_nome) or "SEM NOME"
        if key_e not in total_entregadores:
            total_entregadores[key_e] = {"nome": key_e, "volume_total": 0.0, "comissao_total": 0.0}
        total_entregadores[key_e]["volume_total"] += (calc["base_ent_gf"] + calc["base_ent_pet"] + calc["base_ent_agua"] + calc["base_ent_acucar"])
        total_entregadores[key_e]["comissao_total"] += com_e

        if key_e not in total_refugo:
            total_refugo[key_e] = {"entregador": key_e, "dev_gf": 0.0, "dev_pet": 0.0}
        total_refugo[key_e]["dev_gf"] += _as_float(r.get("dev_gf"), 0.0)
        total_refugo[key_e]["dev_pet"] += _as_float(r.get("dev_pet"), 0.0)

        key_u = _as_str(r.get("usina")) or "SEM USINA"
        if key_u not in total_acucar:
            total_acucar[key_u] = {"usina": key_u, "qtd": 0.0, "comissao": 0.0}
        qtd_ac = _as_float(r.get("acucar_qtd"), 0.0)
        total_acucar[key_u]["qtd"] += qtd_ac
        total_acucar[key_u]["comissao"] += qtd_ac * taxa_acucar

    return {
        "resumo_geral": resumo,
        "total_vendedores": sorted(total_vendedores.values(), key=lambda x: (x["codigo"], x["nome"])),
        "total_entregadores": sorted(total_entregadores.values(), key=lambda x: x["nome"]),
        "total_refugo": sorted(total_refugo.values(), key=lambda x: x["entregador"]),
        "total_acucar": sorted(total_acucar.values(), key=lambda x: x["usina"]),
    }

def _build_relatorio_comissao_pdf(rel, filtro_cod=0, filtro_entregador=""):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo = os.path.join("/tmp", f"relatorio_comissao_{stamp}.pdf")
    doc = SimpleDocTemplate(
        arquivo,
        topMargin=24,
        leftMargin=36,
        rightMargin=36,
        bottomMargin=36
    )
    styles = getSampleStyleSheet()
    elementos = []

    logo_cell = ""
    logo_path = os.path.join(BASE_DIR, "logo.png")
    if os.path.isfile(logo_path):
        try:
            logo_cell = Image(logo_path, width=64, height=64)
        except Exception:
            logo_cell = ""

    dados_empresa = [
        Paragraph("<b>Bebidas Rio Branco</b>", styles["Heading3"]),
        Paragraph("CNPJ: 20.984.401/0001-30", styles["Normal"]),
        Paragraph("Rua Joao Nelson Arcipretti, 278 - Centro, Astorga - PR, 86730-000", styles["Normal"]),
        Paragraph("Site: refrigeranteriobranco.com.br", styles["Normal"]),
        Paragraph("E-mail: contato@refrigeranteriobranco.com.br", styles["Normal"]),
    ]
    cabecalho = Table([[logo_cell, dados_empresa]], colWidths=[72, 390])
    cabecalho.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
    ]))
    elementos.append(cabecalho)
    elementos.append(Spacer(1, 12))
    elementos.append(Paragraph("Relatorio de Comissao", styles["Heading2"]))
    elementos.append(Spacer(1, 8))

    filtro_txt = "Todos"
    if _as_int(filtro_cod, 0) > 0:
        filtro_txt = f"Vendedor codigo {_as_int(filtro_cod, 0)}"
    if _as_str(filtro_entregador):
        filtro_txt = f"Entregador {_as_str(filtro_entregador)}"
    elementos.append(Paragraph(f"Filtro aplicado: {filtro_txt}", styles["Normal"]))
    elementos.append(Paragraph(f"Emitido em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", styles["Normal"]))
    elementos.append(Spacer(1, 10))

    r = rel.get("resumo_geral", {}) or {}
    elementos.append(Paragraph(f"Total de lancamentos: {_as_int(r.get('total_lancamentos'), 0)}", styles["Normal"]))
    elementos.append(Paragraph(f"Base vendedor total: R$ {_as_float(r.get('base_vendedor_total'), 0.0):.2f}", styles["Normal"]))
    elementos.append(Paragraph(f"Comissao vendedor total: R$ {_as_float(r.get('comissao_vendedor_total'), 0.0):.2f}", styles["Normal"]))
    elementos.append(Paragraph(f"Comissao entregador total: R$ {_as_float(r.get('comissao_entregador_total'), 0.0):.2f}", styles["Normal"]))
    elementos.append(Spacer(1, 12))

    tv = rel.get("total_vendedores", []) or []
    if tv:
        elementos.append(Paragraph("Totais por Vendedor", styles["Heading4"]))
        dados = [["Cod", "Nome", "Base", "Comissao"]]
        for x in tv[:80]:
            dados.append([
                str(_as_int(x.get("codigo"), 0)),
                _as_str(x.get("nome"))[:36],
                f"R$ {_as_float(x.get('base_total'),0.0):.2f}",
                f"R$ {_as_float(x.get('comissao_total'),0.0):.2f}",
            ])
        t = Table(dados, colWidths=[50, 190, 110, 110])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        elementos.append(t)
        elementos.append(Spacer(1, 12))

    te = rel.get("total_entregadores", []) or []
    if te:
        elementos.append(Paragraph("Totais por Entregador", styles["Heading4"]))
        dados = [["Nome", "Volume", "Comissao"]]
        for x in te[:80]:
            dados.append([
                _as_str(x.get("nome"))[:42],
                f"{_as_float(x.get('volume_total'),0.0):.2f}",
                f"R$ {_as_float(x.get('comissao_total'),0.0):.2f}",
            ])
        t = Table(dados, colWidths=[230, 100, 130])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        elementos.append(t)

    doc.build(elementos)
    return arquivo

def _vendas_config_defaults():
    return {
        "habilitado": True,
        "source_type": "csv_relatorios_dir",
        "csv_dir": VENDAS_RELATORIOS_DIR,
        "active_cache_id": "",
        "firebird_host": "",
        "firebird_port": 3050,
        "firebird_database": "",
        "firebird_user": "",
        "firebird_password": "",
        "firebird_query": "",
        "updated_at": None,
    }

def _vendas_config_publico(data=None):
    base = _vendas_config_defaults()
    if isinstance(data, dict):
        base.update({
            "habilitado": _as_bool(data.get("habilitado"), True),
            "source_type": _as_str(data.get("source_type")).lower() or "csv_relatorios_dir",
            "csv_dir": _as_str(data.get("csv_dir")) or VENDAS_RELATORIOS_DIR,
            "active_cache_id": _as_str(data.get("active_cache_id")),
            "firebird_host": _as_str(data.get("firebird_host")),
            "firebird_port": _as_int(data.get("firebird_port"), 3050),
            "firebird_database": _as_str(data.get("firebird_database")),
            "firebird_user": _as_str(data.get("firebird_user")),
            "firebird_password": _as_str(data.get("firebird_password")),
            "firebird_query": _as_str(data.get("firebird_query")),
            "updated_at": _fmt_dt(data.get("updated_at")),
        })
    if base["source_type"] not in ("csv_relatorios_dir", "firebird"):
        base["source_type"] = "csv_relatorios_dir"
    return base

def _carregar_vendas_config():
    return _vendas_config_publico(_load_json_file(VENDAS_CONFIG_FILE, {}))

def _persistir_vendas_config(data):
    cfg = _vendas_config_publico(data or {})
    cfg["updated_at"] = _fmt_dt(datetime.datetime.now())
    _save_json_file(VENDAS_CONFIG_FILE, cfg)
    return _carregar_vendas_config()

def _vendas_db_row_to_entry(row):
    item = dict(row or {})
    return {
        "id": _as_str(item.get("id")),
        "source_type": _as_str(item.get("source_type")),
        "source_path": _as_str(item.get("source_path")),
        "source_name": _as_str(item.get("source_name")) or os.path.basename(_as_str(item.get("source_path"))),
        "source_size": _as_int(item.get("source_size"), 0),
        "source_mtime": _fmt_dt(item.get("source_mtime")),
        "source_signature": _as_str(item.get("source_signature")),
        "cache_path": "",
        "cache_exists": True,
        "rows_importadas": _as_int(item.get("rows_importadas"), 0),
        "importado_em": _fmt_dt(item.get("importado_em")),
        "updated_at": _fmt_dt(item.get("updated_at")),
        "status": _as_str(item.get("status")) or "pronto",
        "active": _as_bool(item.get("ativo"), False),
    }

def _vendas_db_list_imports():
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT id, source_type, source_path, source_name, source_size, source_mtime,
                   source_signature, rows_importadas, status, ativo, importado_em, updated_at
            FROM vendas_relatorios_importados
            ORDER BY ativo DESC, importado_em DESC, id DESC
        """)
        return [_vendas_db_row_to_entry(row) for row in (cur.fetchall() or [])]
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def _vendas_db_fetch_import(cache_id):
    cache_id = _as_str(cache_id)
    if not cache_id:
        return None
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT id, source_type, source_path, source_name, source_size, source_mtime,
                   source_signature, rows_importadas, status, ativo, importado_em, updated_at
            FROM vendas_relatorios_importados
            WHERE id=%s
            LIMIT 1
        """, (cache_id,))
        row = cur.fetchone()
        return _vendas_db_row_to_entry(row) if row else None
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def _vendas_db_find_import(source_signature="", source_path=""):
    source_signature = _as_str(source_signature)
    source_path = _as_str(source_path)
    source_path_abs = os.path.abspath(source_path) if source_path else ""
    if not source_signature and not source_path_abs:
        return None
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        if source_signature:
            cur.execute("""
                SELECT id, source_type, source_path, source_name, source_size, source_mtime,
                       source_signature, rows_importadas, status, ativo, importado_em, updated_at
                FROM vendas_relatorios_importados
                WHERE source_signature=%s
                ORDER BY importado_em DESC
                LIMIT 1
            """, (source_signature,))
            row = cur.fetchone()
            if row:
                return _vendas_db_row_to_entry(row)
        if source_path_abs:
            cur.execute("""
                SELECT id, source_type, source_path, source_name, source_size, source_mtime,
                       source_signature, rows_importadas, status, ativo, importado_em, updated_at
                FROM vendas_relatorios_importados
                WHERE source_path=%s
                ORDER BY importado_em DESC
                LIMIT 1
            """, (source_path_abs,))
            row = cur.fetchone()
            if row:
                return _vendas_db_row_to_entry(row)
        return None
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def _vendas_db_set_active_flag(cache_id):
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE vendas_relatorios_importados SET ativo=0")
        if _as_str(cache_id):
            cur.execute("UPDATE vendas_relatorios_importados SET ativo=1, updated_at=NOW() WHERE id=%s", (_as_str(cache_id),))
        conn.commit()
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def _vendas_db_upsert_import_meta(entry):
    payload = dict(entry or {})
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO vendas_relatorios_importados (
                id, source_type, source_path, source_name, source_size, source_mtime,
                source_signature, rows_importadas, status, ativo, importado_em, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                source_type=VALUES(source_type),
                source_path=VALUES(source_path),
                source_name=VALUES(source_name),
                source_size=VALUES(source_size),
                source_mtime=VALUES(source_mtime),
                source_signature=VALUES(source_signature),
                rows_importadas=VALUES(rows_importadas),
                status=VALUES(status),
                ativo=VALUES(ativo),
                importado_em=VALUES(importado_em),
                updated_at=VALUES(updated_at)
        """, (
            _as_str(payload.get("id")),
            _as_str(payload.get("source_type")) or "csv_relatorios_dir",
            _as_str(payload.get("source_path")),
            _as_str(payload.get("source_name")) or os.path.basename(_as_str(payload.get("source_path"))),
            _as_int(payload.get("source_size"), 0),
            payload.get("source_mtime"),
            _as_str(payload.get("source_signature")),
            _as_int(payload.get("rows_importadas"), 0),
            _as_str(payload.get("status")) or "pronto",
            1 if _as_bool(payload.get("ativo"), False) else 0,
            payload.get("importado_em"),
            payload.get("updated_at"),
        ))
        conn.commit()
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def _vendas_db_delete_import(cache_id):
    cache_id = _as_str(cache_id)
    if not cache_id:
        return
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM vendas_relatorio_itens WHERE import_id=%s", (cache_id,))
        cur.execute("DELETE FROM vendas_relatorios_importados WHERE id=%s", (cache_id,))
        conn.commit()
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def _vendas_cache_set_active(cache_id):
    cfg = _carregar_vendas_config()
    cache_id = _as_str(cache_id)
    payload = dict(cfg)
    payload["active_cache_id"] = cache_id
    _vendas_db_set_active_flag(cache_id)
    return _persistir_vendas_config(payload)

def _vendas_cache_registry_load():
    data = _load_json_file(VENDAS_CACHE_INDEX_FILE, {"imports": []}) or {"imports": []}
    imports = data.get("imports")
    data["imports"] = imports if isinstance(imports, list) else []
    return data

def _vendas_cache_registry_save(data):
    payload = data if isinstance(data, dict) else {"imports": []}
    payload["imports"] = payload.get("imports") if isinstance(payload.get("imports"), list) else []
    _save_json_file(VENDAS_CACHE_INDEX_FILE, payload)

def _vendas_cache_entry_publico(entry):
    e = entry if isinstance(entry, dict) else {}
    return {
        "id": _as_str(e.get("id")),
        "source_type": _as_str(e.get("source_type")),
        "source_path": _as_str(e.get("source_path")),
        "source_name": os.path.basename(_as_str(e.get("source_path"))) if _as_str(e.get("source_path")) else "",
        "source_size": _as_int(e.get("source_size"), 0),
        "source_mtime": _fmt_dt(e.get("source_mtime")),
        "cache_path": _as_str(e.get("cache_path")),
        "cache_exists": bool(_as_str(e.get("cache_path")) and os.path.exists(_as_str(e.get("cache_path")))),
        "rows_importadas": _as_int(e.get("rows_importadas"), 0),
        "importado_em": _fmt_dt(e.get("importado_em")),
        "updated_at": _fmt_dt(e.get("updated_at")),
        "status": _as_str(e.get("status")) or "pronto",
        "source_signature": _as_str(e.get("source_signature")),
        "active": bool(e.get("active")),
    }

def _vendas_source_signature(path):
    if not path or not os.path.exists(path):
        return ""
    stat = os.stat(path)
    return f"{os.path.abspath(path)}|{int(stat.st_mtime)}|{int(stat.st_size)}"

def _vendas_csv_nome_valido(nome):
    texto = _as_str(nome)
    if not texto:
        return False
    nome_upper = texto.upper()
    if ":" in texto:
        return False
    if not nome_upper.endswith(".CSV"):
        return False
    return True

def _vendas_source_descriptor(cfg=None):
    cfg = cfg or _carregar_vendas_config()
    source_type = _as_str(cfg.get("source_type")).lower() or "csv_relatorios_dir"
    if source_type == "firebird":
        return {
            "source_type": "firebird",
            "ready": False,
            "message": "Integracao Firebird ainda nao implementada; configuracao reservada para a proxima etapa.",
            "path": "",
            "signature": "",
        }

    csv_dir = _as_str(cfg.get("csv_dir")) or VENDAS_RELATORIOS_DIR
    if not os.path.isdir(csv_dir):
        return {
            "source_type": "csv_relatorios_dir",
            "ready": False,
            "message": f"Diretorio de relatorios nao encontrado: {csv_dir}",
            "path": "",
            "signature": "",
        }

    candidatos = []
    for nome in os.listdir(csv_dir):
        if _vendas_csv_nome_valido(nome):
            path = os.path.join(csv_dir, nome)
            if os.path.isfile(path):
                candidatos.append(path)
    if not candidatos:
        return {
            "source_type": "csv_relatorios_dir",
            "ready": False,
            "message": f"Nenhum CSV valido encontrado em {csv_dir}. Arquivos auxiliares como :Zone.Identifier sao ignorados.",
            "path": "",
            "signature": "",
        }
    candidatos.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    path = candidatos[0]
    stat = os.stat(path)
    return {
        "source_type": "csv_relatorios_dir",
        "ready": True,
        "message": "",
        "path": path,
        "name": os.path.basename(path),
        "size": _as_int(stat.st_size, 0),
        "mtime": _fmt_dt(datetime.datetime.fromtimestamp(stat.st_mtime)),
        "signature": _vendas_source_signature(path),
    }

def _vendas_cache_find_entry(source_signature="", source_path=""):
    registry = _vendas_cache_registry_load()
    source_signature = _as_str(source_signature)
    source_path_abs = os.path.abspath(_as_str(source_path)) if _as_str(source_path) else ""
    for entry in registry.get("imports", []):
        if source_signature and _as_str(entry.get("source_signature")) == source_signature:
            return entry
        if source_path_abs and os.path.abspath(_as_str(entry.get("source_path"))) == source_path_abs:
            return entry
    return None

def _vendas_cache_find_by_id(cache_id):
    return _vendas_db_fetch_import(cache_id)

def _vendas_cache_imports_publicos(cfg=None):
    cfg = cfg or _carregar_vendas_config()
    active_id = _as_str(cfg.get("active_cache_id"))
    itens = []
    for entry in _vendas_db_list_imports():
        row = dict(entry)
        row["active"] = bool(active_id and _as_str(entry.get("id")) == active_id)
        itens.append(_vendas_cache_entry_publico(row))
    return itens

def _vendas_normalizar_linha(raw):
    vendedor_info = _split_codigo_nome(raw.get("Vendedor Pedido"))
    vendedor_key = " - ".join(part for part in (vendedor_info["codigo"], vendedor_info["nome"]) if part) or "SEM VENDEDOR"
    return {
        "data": _fmt_date(_parse_data_br(raw.get("Data"))) or _as_str(raw.get("Data")),
        "vendedor_key": vendedor_key,
        "vendedor_codigo": vendedor_info["codigo"],
        "vendedor_nome": vendedor_info["nome"] or vendedor_key,
        "numero_nf": _as_str(raw.get("Número nf")),
        "cliente": _as_str(raw.get("Cliente")),
        "cidade": _as_str(raw.get("Cidade")),
        "produto": _as_str(raw.get("Produto")),
        "tipo_operacao": _as_str(raw.get("Tipo Operação")),
        "condicao": _as_str(raw.get("Condição")),
        "quantidade": _as_float_br(raw.get("Quantidade"), 0.0),
        "litros": _as_float_br(raw.get("Litro"), 0.0),
        "caixas": _as_float_br(raw.get("Caixa Física"), 0.0),
        "valor_venda": _as_float_br(raw.get("Valor Venda"), 0.0),
        "valor_devolvido": _as_float_br(raw.get("Valor Devolvido"), 0.0),
        "quantidade_devolvida": _as_float_br(raw.get("Quantidade Devolvida"), 0.0),
        "litro_devolvido": _as_float_br(raw.get("Litro Devolvido"), 0.0),
        "caixa_devolvida": _as_float_br(raw.get("Caixa Fisica Devolvida"), 0.0),
    }

def _vendas_importar_csv_para_cache(source_path, source_type="csv_relatorios_dir"):
    source_path = _as_str(source_path)
    if not source_path or not os.path.exists(source_path):
        raise FileNotFoundError("Arquivo de vendas nao encontrado para importacao.")

    source_signature = _vendas_source_signature(source_path)
    cache_id = hashlib.sha1(source_signature.encode("utf-8")).hexdigest()[:16]
    stat = os.stat(source_path)
    agora = datetime.datetime.now()
    meta = {
        "id": cache_id,
        "source_type": source_type,
        "source_path": os.path.abspath(source_path),
        "source_name": os.path.basename(source_path),
        "source_size": _as_int(stat.st_size, 0),
        "source_mtime": datetime.datetime.fromtimestamp(stat.st_mtime),
        "source_signature": source_signature,
        "rows_importadas": 0,
        "importado_em": agora,
        "updated_at": agora,
        "status": "importando",
        "ativo": False,
    }
    _vendas_db_upsert_import_meta(meta)

    conn = None
    cur = None
    total_rows = 0
    lote = []

    def _flush_rows():
        nonlocal lote, total_rows
        if not lote:
            return
        cur.executemany("""
            INSERT INTO vendas_relatorio_itens (
                import_id, data_ref, data_texto, vendedor_key, vendedor_key_upper, vendedor_codigo,
                vendedor_nome, numero_nf, cliente, cliente_norm, cidade, produto, tipo_operacao,
                condicao, quantidade, litros, caixas, valor_venda, valor_devolvido, valor_liquido,
                quantidade_devolvida, litro_devolvido, caixa_devolvida
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, lote)
        total_rows += len(lote)
        lote = []

    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM vendas_relatorio_itens WHERE import_id=%s", (cache_id,))
        with _vendas_relatorio_open(source_path) as handle:
            leitor = csv.DictReader(handle, delimiter=";")
            for raw in leitor:
                row = _vendas_normalizar_linha(raw)
                valor_liquido = round(_as_float(row.get("valor_venda"), 0.0) - _as_float(row.get("valor_devolvido"), 0.0), 2)
                data_ref = _parse_data_br(row.get("data"))
                vendedor_key = _as_str(row.get("vendedor_key")) or "SEM VENDEDOR"
                cliente = _as_str(row.get("cliente"))
                lote.append((
                    cache_id,
                    data_ref,
                    _as_str(row.get("data")),
                    vendedor_key,
                    vendedor_key.upper(),
                    _as_str(row.get("vendedor_codigo")),
                    _as_str(row.get("vendedor_nome")) or vendedor_key,
                    _as_str(row.get("numero_nf")),
                    cliente,
                    cliente.upper(),
                    _as_str(row.get("cidade")),
                    _as_str(row.get("produto")),
                    _as_str(row.get("tipo_operacao")),
                    _as_str(row.get("condicao")),
                    round(_as_float(row.get("quantidade"), 0.0), 3),
                    round(_as_float(row.get("litros"), 0.0), 3),
                    round(_as_float(row.get("caixas"), 0.0), 3),
                    round(_as_float(row.get("valor_venda"), 0.0), 2),
                    round(_as_float(row.get("valor_devolvido"), 0.0), 2),
                    valor_liquido,
                    round(_as_float(row.get("quantidade_devolvida"), 0.0), 3),
                    round(_as_float(row.get("litro_devolvido"), 0.0), 3),
                    round(_as_float(row.get("caixa_devolvida"), 0.0), 3),
                ))
                if len(lote) >= 500:
                    _flush_rows()
        _flush_rows()
        conn.commit()
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        meta["status"] = "erro"
        meta["updated_at"] = datetime.datetime.now()
        _vendas_db_upsert_import_meta(meta)
        raise
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    meta["rows_importadas"] = total_rows
    meta["status"] = "pronto"
    meta["updated_at"] = datetime.datetime.now()
    _vendas_db_upsert_import_meta(meta)
    return _vendas_db_fetch_import(cache_id) or _vendas_db_row_to_entry(meta)

def _vendas_salvar_upload_csv(file_storage):
    nome = secure_filename(getattr(file_storage, "filename", "") or "relatorio_vendas.csv") or "relatorio_vendas.csv"
    if not nome.lower().endswith(".csv"):
        nome = f"{nome}.csv"
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = os.path.join(VENDAS_UPLOADS_DIR, f"{stamp}_{nome}")
    file_storage.save(destino)
    return destino

def _vendas_obter_cache_ativo(force_refresh=False):
    cfg = _carregar_vendas_config()
    if not _as_bool(cfg.get("habilitado"), True):
        raise RuntimeError("Integracao de vendas desativada na configuracao.")
    active_id = _as_str(cfg.get("active_cache_id"))
    active_entry = _vendas_cache_find_by_id(active_id) if active_id else None
    if active_entry and not force_refresh:
        return active_entry, {
            "source_type": _as_str(active_entry.get("source_type")) or _as_str(cfg.get("source_type")),
            "ready": True,
            "message": "",
            "path": _as_str(active_entry.get("source_path")),
            "name": os.path.basename(_as_str(active_entry.get("source_path"))),
            "size": _as_int(active_entry.get("source_size"), 0),
            "mtime": _fmt_dt(active_entry.get("source_mtime")),
            "signature": _as_str(active_entry.get("source_signature")),
        }, cfg
    source = _vendas_source_descriptor(cfg)
    if not source.get("ready"):
        imports = _vendas_db_list_imports()
        if imports:
            raise RuntimeError("Nenhum relatorio importado esta marcado como em uso. Ative um relatorio em Config > Vendas.")
        raise RuntimeError(source.get("message") or "Fonte de vendas indisponivel.")
    entry = None if force_refresh else _vendas_db_find_import(source_signature=source.get("signature"), source_path=source.get("path"))
    if force_refresh or entry is None:
        entry = _vendas_importar_csv_para_cache(source.get("path"), source.get("source_type"))
    return entry, source, cfg

def _vendas_relatorio_csv_path():
    if not os.path.isdir(VENDAS_RELATORIOS_DIR):
        return ""
    candidatos = []
    for nome in os.listdir(VENDAS_RELATORIOS_DIR):
        nome_upper = nome.upper()
        if not nome_upper.endswith(".CSV"):
            continue
        candidatos.append(os.path.join(VENDAS_RELATORIOS_DIR, nome))
    if not candidatos:
        return ""
    candidatos.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    return candidatos[0]

def _vendas_relatorio_open(csv_path):
    return open(csv_path, "r", encoding="cp1252", errors="replace", newline="")

def _split_codigo_nome(value):
    texto = _as_str(value)
    if not texto:
        return {"codigo": "", "nome": ""}
    if "-" not in texto:
        return {"codigo": "", "nome": texto}
    codigo, nome = texto.split("-", 1)
    return {"codigo": _as_str(codigo), "nome": _as_str(nome)}

def _parse_data_br(value):
    texto = _as_str(value)
    if not texto:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(texto[:10], fmt).date()
        except Exception:
            continue
    return None

def _vendas_relatorio_empty_totais():
    return {
        "notas": 0,
        "clientes": 0,
        "itens": 0,
        "quantidade": 0.0,
        "litros": 0.0,
        "caixas": 0.0,
        "valor_venda": 0.0,
        "valor_devolvido": 0.0,
        "valor_liquido": 0.0,
        "quantidade_devolvida": 0.0,
        "litro_devolvido": 0.0,
        "caixa_devolvida": 0.0,
    }

def _vendas_relatorio_publico_totais(totais):
    data = dict(_vendas_relatorio_empty_totais())
    if isinstance(totais, dict):
        data.update(totais)
    return {
        "notas": _as_int(data.get("notas"), 0),
        "clientes": _as_int(data.get("clientes"), 0),
        "itens": _as_int(data.get("itens"), 0),
        "quantidade": round(_as_float(data.get("quantidade"), 0.0), 3),
        "litros": round(_as_float(data.get("litros"), 0.0), 3),
        "caixas": round(_as_float(data.get("caixas"), 0.0), 3),
        "valor_venda": round(_as_float(data.get("valor_venda"), 0.0), 2),
        "valor_devolvido": round(_as_float(data.get("valor_devolvido"), 0.0), 2),
        "valor_liquido": round(_as_float(data.get("valor_liquido"), 0.0), 2),
        "quantidade_devolvida": round(_as_float(data.get("quantidade_devolvida"), 0.0), 3),
        "litro_devolvido": round(_as_float(data.get("litro_devolvido"), 0.0), 3),
        "caixa_devolvida": round(_as_float(data.get("caixa_devolvida"), 0.0), 3),
    }

def _vendas_relatorio_row_publico(row):
    return {
        "data": _as_str(row.get("data")),
        "numero_nf": _as_str(row.get("numero_nf")),
        "cliente": _as_str(row.get("cliente")),
        "cidade": _as_str(row.get("cidade")),
        "produto": _as_str(row.get("produto")),
        "tipo_operacao": _as_str(row.get("tipo_operacao")),
        "condicao": _as_str(row.get("condicao")),
        "quantidade": round(_as_float(row.get("quantidade"), 0.0), 3),
        "litros": round(_as_float(row.get("litros"), 0.0), 3),
        "caixas": round(_as_float(row.get("caixas"), 0.0), 3),
        "valor_venda": round(_as_float(row.get("valor_venda"), 0.0), 2),
        "valor_devolvido": round(_as_float(row.get("valor_devolvido"), 0.0), 2),
        "valor_liquido": round(_as_float(row.get("valor_liquido"), 0.0), 2),
    }

def _coletar_relatorio_vendas(filtro_vendedor="", data_inicio=None, data_fim=None, limite_detalhes=300):
    cache_entry, source, cfg = _vendas_obter_cache_ativo(force_refresh=False)

    filtro_vendedor = _as_str(filtro_vendedor).upper()
    if isinstance(data_inicio, str):
        data_inicio = _parse_data_br(data_inicio)
    if isinstance(data_fim, str):
        data_fim = _parse_data_br(data_fim)
    limite_detalhes = max(50, min(_as_int(limite_detalhes, 300), 1000))
    where = ["import_id=%s"]
    params = [_as_str(cache_entry.get("id"))]
    if data_inicio:
        where.append("data_ref IS NOT NULL AND data_ref >= %s")
        params.append(data_inicio)
    if data_fim:
        where.append("data_ref IS NOT NULL AND data_ref <= %s")
        params.append(data_fim)
    if filtro_vendedor:
        where.append("vendedor_key_upper = %s")
        params.append(filtro_vendedor)
    where_sql = " AND ".join(where)

    conn = None
    cur = None
    detalhes = []
    try:
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute(f"""
            SELECT
                COUNT(*) AS itens,
                COUNT(DISTINCT NULLIF(cliente_norm, '')) AS clientes,
                COUNT(DISTINCT NULLIF(numero_nf, '')) AS notas,
                COALESCE(SUM(quantidade), 0) AS quantidade,
                COALESCE(SUM(litros), 0) AS litros,
                COALESCE(SUM(caixas), 0) AS caixas,
                COALESCE(SUM(valor_venda), 0) AS valor_venda,
                COALESCE(SUM(valor_devolvido), 0) AS valor_devolvido,
                COALESCE(SUM(valor_liquido), 0) AS valor_liquido,
                COALESCE(SUM(quantidade_devolvida), 0) AS quantidade_devolvida,
                COALESCE(SUM(litro_devolvido), 0) AS litro_devolvido,
                COALESCE(SUM(caixa_devolvida), 0) AS caixa_devolvida
            FROM vendas_relatorio_itens
            WHERE {where_sql}
        """, tuple(params))
        totais = _vendas_relatorio_publico_totais(cur.fetchone() or {})

        cur.execute(f"""
            SELECT
                vendedor_key AS chave,
                MAX(vendedor_codigo) AS codigo,
                MAX(vendedor_nome) AS nome,
                COUNT(*) AS itens,
                COUNT(DISTINCT NULLIF(cliente_norm, '')) AS clientes,
                COUNT(DISTINCT NULLIF(numero_nf, '')) AS notas,
                COALESCE(SUM(quantidade), 0) AS quantidade,
                COALESCE(SUM(litros), 0) AS litros,
                COALESCE(SUM(caixas), 0) AS caixas,
                COALESCE(SUM(valor_venda), 0) AS valor_venda,
                COALESCE(SUM(valor_devolvido), 0) AS valor_devolvido,
                COALESCE(SUM(valor_liquido), 0) AS valor_liquido,
                COALESCE(SUM(quantidade_devolvida), 0) AS quantidade_devolvida,
                COALESCE(SUM(litro_devolvido), 0) AS litro_devolvido,
                COALESCE(SUM(caixa_devolvida), 0) AS caixa_devolvida
            FROM vendas_relatorio_itens
            WHERE {where_sql}
            GROUP BY vendedor_key
            ORDER BY valor_liquido DESC, nome ASC, codigo ASC
        """, tuple(params))
        vendedores = []
        for row in (cur.fetchall() or []):
            vendedores.append({
                "chave": _as_str(row.get("chave")) or "SEM VENDEDOR",
                "codigo": _as_str(row.get("codigo")),
                "nome": _as_str(row.get("nome")) or _as_str(row.get("chave")) or "SEM VENDEDOR",
                **_vendas_relatorio_publico_totais(row),
            })

        cur.execute(f"""
            SELECT
                cidade AS chave,
                cidade AS nome,
                COUNT(*) AS itens,
                COUNT(DISTINCT NULLIF(cliente_norm, '')) AS clientes,
                COUNT(DISTINCT NULLIF(numero_nf, '')) AS notas,
                COALESCE(SUM(quantidade), 0) AS quantidade,
                COALESCE(SUM(litros), 0) AS litros,
                COALESCE(SUM(caixas), 0) AS caixas,
                COALESCE(SUM(valor_venda), 0) AS valor_venda,
                COALESCE(SUM(valor_devolvido), 0) AS valor_devolvido,
                COALESCE(SUM(valor_liquido), 0) AS valor_liquido,
                COALESCE(SUM(quantidade_devolvida), 0) AS quantidade_devolvida,
                COALESCE(SUM(litro_devolvido), 0) AS litro_devolvido,
                COALESCE(SUM(caixa_devolvida), 0) AS caixa_devolvida
            FROM vendas_relatorio_itens
            WHERE {where_sql}
            GROUP BY cidade
            ORDER BY valor_liquido DESC, nome ASC
        """, tuple(params))
        cidades = []
        for row in (cur.fetchall() or []):
            cidades.append({
                "chave": _as_str(row.get("chave")) or "SEM CIDADE",
                "nome": _as_str(row.get("nome")) or "SEM CIDADE",
                **_vendas_relatorio_publico_totais(row),
            })

        cur.execute(f"""
            SELECT
                produto AS chave,
                produto AS nome,
                COUNT(*) AS itens,
                COUNT(DISTINCT NULLIF(cliente_norm, '')) AS clientes,
                COUNT(DISTINCT NULLIF(numero_nf, '')) AS notas,
                COALESCE(SUM(quantidade), 0) AS quantidade,
                COALESCE(SUM(litros), 0) AS litros,
                COALESCE(SUM(caixas), 0) AS caixas,
                COALESCE(SUM(valor_venda), 0) AS valor_venda,
                COALESCE(SUM(valor_devolvido), 0) AS valor_devolvido,
                COALESCE(SUM(valor_liquido), 0) AS valor_liquido,
                COALESCE(SUM(quantidade_devolvida), 0) AS quantidade_devolvida,
                COALESCE(SUM(litro_devolvido), 0) AS litro_devolvido,
                COALESCE(SUM(caixa_devolvida), 0) AS caixa_devolvida
            FROM vendas_relatorio_itens
            WHERE {where_sql}
            GROUP BY produto
            ORDER BY valor_liquido DESC, nome ASC
        """, tuple(params))
        produtos = []
        for row in (cur.fetchall() or []):
            produtos.append({
                "chave": _as_str(row.get("chave")) or "SEM PRODUTO",
                "nome": _as_str(row.get("nome")) or "SEM PRODUTO",
                **_vendas_relatorio_publico_totais(row),
            })

        if filtro_vendedor:
            cur.execute(f"""
                SELECT
                    data_texto AS data, numero_nf, cliente, cidade, produto,
                    tipo_operacao, condicao, quantidade, litros, caixas,
                    valor_venda, valor_devolvido, valor_liquido
                FROM vendas_relatorio_itens
                WHERE {where_sql}
                ORDER BY data_ref DESC, id DESC
                LIMIT %s
            """, tuple(params + [limite_detalhes]))
            detalhes = [_vendas_relatorio_row_publico(item) for item in (cur.fetchall() or [])]
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return {
        "arquivo": {
            "nome": _as_str(source.get("name")) or os.path.basename(_as_str(cache_entry.get("source_path"))),
            "tamanho_bytes": _as_int(source.get("size"), _as_int(cache_entry.get("source_size"), 0)),
            "atualizado_em": _as_str(source.get("mtime")) or _fmt_dt(cache_entry.get("source_mtime")),
        },
        "filtros": {
            "vendedor": filtro_vendedor,
            "data_inicio": _fmt_date(data_inicio),
            "data_fim": _fmt_date(data_fim),
            "limite_detalhes": limite_detalhes,
        },
        "cache": _vendas_cache_entry_publico(cache_entry),
        "fonte": {
            "source_type": _as_str(cfg.get("source_type")),
            "ready": bool(source.get("ready")),
            "message": _as_str(source.get("message")),
        },
        "resumo_geral": totais,
        "vendedores": vendedores,
        "cidades": cidades,
        "produtos": produtos,
        "detalhes_vendedor": detalhes,
        "detalhes_limitados": bool(filtro_vendedor and len(detalhes) >= limite_detalhes),
    }

@app.route("/api/comissao/relatorios", methods=["GET"])
def relatorios_comissao():
    filtro_cod = _as_int(request.args.get("cod_vendedor"), 0)
    filtro_entregador = _as_str(request.args.get("entregador"))
    return jsonify(_coletar_relatorios_comissao(filtro_cod, filtro_entregador))

@app.route("/api/comissao/relatorios/pdf", methods=["GET"])
def relatorios_comissao_pdf():
    filtro_cod = _as_int(request.args.get("cod_vendedor"), 0)
    filtro_entregador = _as_str(request.args.get("entregador"))
    if filtro_cod <= 0 and not filtro_entregador:
        return jsonify({"erro": "filtre por vendedor ou entregador para imprimir"}), 400
    rel = _coletar_relatorios_comissao(filtro_cod, filtro_entregador)
    arquivo = _build_relatorio_comissao_pdf(rel, filtro_cod, filtro_entregador)
    return send_file(arquivo, as_attachment=False, mimetype="application/pdf")

@app.route("/api/vendas/relatorio", methods=["GET"])
def relatorio_vendas():
    try:
        payload = _coletar_relatorio_vendas(
            filtro_vendedor=request.args.get("vendedor"),
            data_inicio=request.args.get("data_inicio"),
            data_fim=request.args.get("data_fim"),
            limite_detalhes=request.args.get("limite"),
        )
    except FileNotFoundError as exc:
        return jsonify({"erro": str(exc)}), 404
    except Exception as exc:
        return jsonify({"erro": f"Falha ao ler relatorio de vendas: {str(exc)}"}), 500
    return jsonify(payload)

@app.route("/api/vendas/config", methods=["GET", "PUT"])
def vendas_config_api():
    if request.method == "GET":
        cfg = _carregar_vendas_config()
        source = _vendas_source_descriptor(cfg)
        return jsonify({
            "config": cfg,
            "fonte": source,
            "imports": _vendas_cache_imports_publicos(cfg),
        })

    data = request.get_json(silent=True) or {}
    cfg = _persistir_vendas_config(data)
    source = _vendas_source_descriptor(cfg)
    return jsonify({
        "ok": True,
        "config": cfg,
        "fonte": source,
        "imports": _vendas_cache_imports_publicos(cfg),
    })

@app.route("/api/vendas/cache/importar", methods=["POST"])
def vendas_cache_importar():
    try:
        file_storage = request.files.get("arquivo") or request.files.get("csv")
        if file_storage and getattr(file_storage, "filename", ""):
            source_path = _vendas_salvar_upload_csv(file_storage)
            entry = _vendas_importar_csv_para_cache(source_path, "csv_upload")
            cfg = _vendas_cache_set_active(_as_str(entry.get("id")))
            source = {
                "source_type": "csv_upload",
                "ready": True,
                "message": "",
                "path": _as_str(entry.get("source_path")),
                "name": os.path.basename(_as_str(entry.get("source_path"))),
                "size": _as_int(entry.get("source_size"), 0),
                "mtime": _fmt_dt(entry.get("source_mtime")),
                "signature": _as_str(entry.get("source_signature")),
            }
        else:
            entry, source, cfg = _vendas_obter_cache_ativo(force_refresh=True)
            cfg = _vendas_cache_set_active(_as_str(entry.get("id")))
    except FileNotFoundError as exc:
        return jsonify({"erro": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        return jsonify({"erro": f"Falha ao importar relatorio de vendas: {str(exc)}"}), 500

    return jsonify({
        "ok": True,
        "config": cfg,
        "fonte": source,
        "cache": _vendas_cache_entry_publico(entry),
        "imports": _vendas_cache_imports_publicos(cfg),
    })

@app.route("/api/vendas/cache/<cache_id>/ativar", methods=["PUT"])
def vendas_cache_ativar(cache_id):
    entry = _vendas_cache_find_by_id(cache_id)
    if entry is None:
        return jsonify({"erro": "cache de vendas nao encontrado"}), 404
    cfg = _vendas_cache_set_active(cache_id)
    source = {
        "source_type": _as_str(entry.get("source_type")),
        "ready": True,
        "message": "",
        "path": _as_str(entry.get("source_path")),
        "name": os.path.basename(_as_str(entry.get("source_path"))),
        "size": _as_int(entry.get("source_size"), 0),
        "mtime": _fmt_dt(entry.get("source_mtime")),
        "signature": _as_str(entry.get("source_signature")),
    }
    return jsonify({
        "ok": True,
        "config": cfg,
        "fonte": source,
        "imports": _vendas_cache_imports_publicos(cfg),
    })

@app.route("/api/vendas/cache/<cache_id>", methods=["DELETE"])
def vendas_cache_excluir(cache_id):
    cache_id = _as_str(cache_id)
    cfg = _carregar_vendas_config()
    removido = _vendas_cache_find_by_id(cache_id)
    if removido is None:
        return jsonify({"erro": "cache de vendas nao encontrado"}), 404

    source_path = _as_str(removido.get("source_path"))
    if _as_str(removido.get("source_type")) == "csv_upload" and source_path and os.path.exists(source_path):
        try:
            os.remove(source_path)
        except Exception:
            pass
    _vendas_db_delete_import(cache_id)
    if _as_str(cfg.get("active_cache_id")) == cache_id:
        cfg = _vendas_cache_set_active("")
    return jsonify({
        "ok": True,
        "config": cfg,
        "imports": _vendas_cache_imports_publicos(cfg),
    })

@app.route("/api/<tabela>", methods=["GET"])
def listar_generico(tabela):
    permitidas = ["cargas", "motoristas", "veiculos", "conferentes"]
    if tabela not in permitidas:
        return jsonify({"erro": "Tabela não permitida"}), 400

    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(f"SELECT * FROM {tabela}")
    dados = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(dados)

@app.route("/api/<tabela>", methods=["POST"])
def criar_generico(tabela):
    permitidas = ["cargas", "motoristas", "veiculos", "conferentes"]
    if tabela not in permitidas:
        return jsonify({"erro": "Tabela não permitida"}), 400

    data = request.json or {}
    conn = get_conn()
    cursor = conn.cursor()

    if tabela == "veiculos":
        cursor.execute(
            """
            INSERT INTO veiculos (nome, placa, modelo, km_atual, intervalo_manut_km, intervalo_oleo_km)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (data.get("nome"), data.get("placa"), data.get("modelo"), data.get("km_atual"), data.get("intervalo_manut_km"), data.get("intervalo_oleo_km"))
        )
    else:
        cursor.execute(f"INSERT INTO {tabela} (nome) VALUES (%s)", (data.get("nome"),))

    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/<tabela>/<int:id>", methods=["PUT"])
def atualizar_generico(tabela, id):
    permitidas = ["cargas", "motoristas", "veiculos", "conferentes"]
    if tabela not in permitidas:
        return jsonify({"erro": "Tabela inválida"}), 400

    data = request.json or {}
    conn = get_conn()
    cursor = conn.cursor()

    if tabela == "veiculos":
        cursor.execute(
            """
            UPDATE veiculos
            SET nome=%s, placa=%s, modelo=%s, km_atual=%s, intervalo_manut_km=%s, intervalo_oleo_km=%s
            WHERE id=%s
            """,
            (data.get("nome"), data.get("placa"), data.get("modelo"), data.get("km_atual"), data.get("intervalo_manut_km"), data.get("intervalo_oleo_km"), id)
        )
    else:
        cursor.execute(f"UPDATE {tabela} SET nome=%s WHERE id=%s", (data.get("nome"), id))

    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/<tabela>/<int:id>", methods=["DELETE"])
def deletar_generico(tabela, id):
    permitidas = ["cargas", "motoristas", "veiculos", "conferentes"]
    if tabela not in permitidas:
        return jsonify({"erro": "Tabela inválida"}), 400

    usuario = _usuario_ator_req()
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    if tabela == "veiculos":
        cursor.execute("SELECT id, nome, placa, modelo FROM veiculos WHERE id=%s", (id,))
    else:
        cursor.execute(f"SELECT id, nome FROM {tabela} WHERE id=%s", (id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return jsonify({"erro": "registro nao encontrado"}), 404

    cursor.execute(f"DELETE FROM {tabela} WHERE id=%s", (id,))
    if tabela == "veiculos":
        descricao = f"veiculo id={id} nome={_as_str(row.get('nome'))} placa={_as_str(row.get('placa'))} modelo={_as_str(row.get('modelo'))}"
    else:
        descricao = f"{tabela[:-1]} id={id} nome={_as_str(row.get('nome'))}"
    _registrar_log_exclusao(cursor, usuario, tabela, id, descricao)
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"ok": True})



# =========================================================
# (7.5) GESTÃO DE FROTA (PERSISTÊNCIA)
# =========================================================
@app.route("/api/abastecimentos", methods=["GET"])
def listar_abastecimentos():
    status_filtro = _as_str(request.args.get("status"))

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    sql = """
        SELECT
            a.id,
            a.veiculo_id,
            a.km,
            a.posto,
            a.combustivel_tipo,
            a.chave_acesso_nfe,
            a.numero_nota,
            a.emitente_nome,
            a.valor,
            a.quantidade_litros,
            a.status,
            a.data_liberacao,
            a.data_abastecimento,
            v.nome AS veiculo_nome,
            v.placa,
            v.modelo
        FROM abastecimentos a
        LEFT JOIN veiculos v ON v.id = a.veiculo_id
    """
    params = []
    if status_filtro:
        sql += " WHERE a.status = %s"
        params.append(status_filtro)
    sql += " ORDER BY a.veiculo_id ASC, a.km ASC, a.id ASC"
    cur.execute(sql, tuple(params))
    rows = cur.fetchall() or []
    cur.close()
    conn.close()

    # Calcula histórico de km/l por veículo com base em abastecimentos concluídos.
    prev_km_by_veiculo = {}
    metricas = {}
    for r in rows:
        rid = _as_int(r.get("id"), 0)
        vid = _as_int(r.get("veiculo_id"), 0)
        status = _as_str(r.get("status")).lower()
        combustivel_tipo = _normalizar_combustivel_tipo(r.get("combustivel_tipo"))
        km = _as_int(r.get("km"), 0)
        qtd = _as_float(r.get("quantidade_litros"), 0.0)

        km_rodado = None
        km_l = None
        if status == "abastecido" and combustivel_tipo == "diesel":
            prev_km = prev_km_by_veiculo.get(vid)
            if prev_km is not None:
                km_rodado_calc = km - prev_km
                if km_rodado_calc > 0:
                    km_rodado = km_rodado_calc
                    if qtd > 0:
                        km_l = km_rodado_calc / qtd
            prev_km_by_veiculo[vid] = km
        metricas[rid] = {"km_rodado": km_rodado, "km_l": km_l}

    # Entrega em ordem mais recente primeiro.
    out = []
    for r in sorted(rows, key=lambda x: _as_int(x.get("id"), 0), reverse=True):
        rid = _as_int(r.get("id"), 0)
        out.append({
            "id": rid,
            "veiculo_id": _as_int(r.get("veiculo_id"), 0),
            "veiculo_nome": r.get("veiculo_nome") or "",
            "placa": r.get("placa") or "",
            "modelo": r.get("modelo") or "",
            "km": _as_int(r.get("km"), 0),
            "posto": _as_str(r.get("posto")),
            "combustivel_tipo": _normalizar_combustivel_tipo(r.get("combustivel_tipo")),
            "chave_acesso_nfe": _normalizar_chave_acesso_nfe(r.get("chave_acesso_nfe")),
            "numero_nota": _as_str(r.get("numero_nota")),
            "emitente_nome": _as_str(r.get("emitente_nome")),
            "valor": _as_float(r.get("valor"), 0.0) if r.get("valor") is not None else None,
            "quantidade_litros": _as_float(r.get("quantidade_litros"), 0.0) if r.get("quantidade_litros") is not None else None,
            "status": _as_str(r.get("status")) or "liberado",
            "data_liberacao": _fmt_dt(r.get("data_liberacao")),
            "data_abastecimento": _fmt_dt(r.get("data_abastecimento")),
            "km_rodado": metricas.get(rid, {}).get("km_rodado"),
            "km_l": metricas.get(rid, {}).get("km_l"),
            "pdf_url": f"/api/abastecimentos/{rid}/pdf"
        })
    return jsonify(out)

@app.route("/api/abastecimentos/liberar", methods=["POST"])
def liberar_abastecimento():
    data = request.json or {}
    veiculo_id = _as_int(data.get("veiculo_id"), 0)
    km = _as_int(data.get("km"), 0)
    posto = _as_str(data.get("posto"))
    combustivel_tipo = _normalizar_combustivel_tipo(data.get("combustivel_tipo"))
    chave_acesso_nfe = _normalizar_chave_acesso_nfe(data.get("chave_acesso_nfe"))
    numero_nota = _as_str(data.get("numero_nota"))
    emitente_nome = _as_str(data.get("emitente_nome"))

    if veiculo_id <= 0:
        return jsonify({"erro": "veiculo_id inválido"}), 400
    if km <= 0:
        return jsonify({"erro": "km inválido"}), 400
    if not posto:
        return jsonify({"erro": "posto é obrigatório"}), 400

    conn = get_conn()
    cur = conn.cursor()
    try:
        try:
            _validar_nota_duplicada_abastecimento(cur, numero_nota=numero_nota, chave_acesso_nfe=chave_acesso_nfe)
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 409

        cur.execute(
            """
            UPDATE veiculos
            SET km_atual = CASE
                WHEN km_atual IS NULL OR km_atual < %s THEN %s
                ELSE km_atual
            END
            WHERE id = %s
            """,
            (km, km, veiculo_id)
        )
        cur.execute(
            """
            INSERT INTO abastecimentos
                (veiculo_id, km, posto, combustivel_tipo, chave_acesso_nfe, numero_nota, emitente_nome, status, data_liberacao)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, 'liberado', NOW())
            """,
            (veiculo_id, km, posto, combustivel_tipo, chave_acesso_nfe, numero_nota, emitente_nome)
        )
        abastecimento_id = cur.lastrowid
        conn.commit()
    finally:
        cur.close()
        conn.close()

    # Gera o PDF imediatamente para impressão/assinatura.
    conn2 = get_conn()
    cur2 = conn2.cursor(dictionary=True)
    cur2.execute("""
        SELECT
            a.*,
            v.nome AS veiculo_nome,
            v.placa,
            v.modelo
        FROM abastecimentos a
        LEFT JOIN veiculos v ON v.id = a.veiculo_id
        WHERE a.id = %s
    """, (abastecimento_id,))
    row = cur2.fetchone()
    cur2.close()
    conn2.close()
    if row:
        _build_abastecimento_pdf(row)

    return jsonify({
        "ok": True,
        "id": abastecimento_id,
        "status": "liberado",
        "pdf_url": f"/api/abastecimentos/{abastecimento_id}/pdf"
    })

@app.route("/api/abastecimentos/<int:abastecimento_id>/abastecer", methods=["PUT"])
def concluir_abastecimento(abastecimento_id):
    data = request.json or {}
    valor = _as_float(data.get("valor"), 0.0)
    quantidade_litros = _as_float(data.get("quantidade_litros"), 0.0)
    combustivel_tipo = _normalizar_combustivel_tipo(data.get("combustivel_tipo"))
    chave_acesso_nfe = _normalizar_chave_acesso_nfe(data.get("chave_acesso_nfe"))
    numero_nota = _as_str(data.get("numero_nota"))
    emitente_nome = _as_str(data.get("emitente_nome"))

    if valor <= 0:
        return jsonify({"erro": "valor inválido"}), 400
    if quantidade_litros <= 0:
        return jsonify({"erro": "quantidade_litros inválido"}), 400

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, veiculo_id, km, status FROM abastecimentos WHERE id=%s", (abastecimento_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({"erro": "abastecimento não encontrado"}), 404
    if _as_str(row.get("status")).lower() != "liberado":
        cur.close()
        conn.close()
        return jsonify({"erro": "somente status liberado pode ser concluído"}), 400

    try:
        _validar_nota_duplicada_abastecimento(
            cur,
            numero_nota=numero_nota,
            chave_acesso_nfe=chave_acesso_nfe,
            exclude_id=abastecimento_id,
        )
    except ValueError as exc:
        cur.close()
        conn.close()
        return jsonify({"erro": str(exc)}), 409

    veiculo_id = _as_int(row.get("veiculo_id"), 0)
    km = _as_int(row.get("km"), 0)

    cur.execute(
        """
        UPDATE abastecimentos
        SET
            valor=%s,
            quantidade_litros=%s,
            combustivel_tipo=%s,
            chave_acesso_nfe=%s,
            numero_nota=%s,
            emitente_nome=%s,
            status='abastecido',
            data_abastecimento=NOW()
        WHERE id=%s
        """,
        (valor, quantidade_litros, combustivel_tipo, chave_acesso_nfe, numero_nota, emitente_nome, abastecimento_id)
    )
    if veiculo_id > 0 and km > 0:
        cur.execute(
            """
            UPDATE veiculos
            SET km_atual = CASE
                WHEN km_atual IS NULL OR km_atual < %s THEN %s
                ELSE km_atual
            END
            WHERE id = %s
            """,
            (km, km, veiculo_id)
        )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True, "id": abastecimento_id, "status": "abastecido"})

@app.route("/api/abastecimentos/<int:abastecimento_id>/importar_nfe", methods=["POST"])
def importar_nfe_abastecimento(abastecimento_id):
    payload = request.form.to_dict(flat=True) if request.form else (request.get_json(silent=True) or {})
    chave_acesso_esperada = _normalizar_chave_acesso_nfe(payload.get("chave_acesso_esperada"))
    combustivel_tipo = payload.get("combustivel_tipo")

    try:
        xml_text, _arquivo_origem = _ler_xml_nfe_requisicao()
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400

    if not xml_text:
        return jsonify({"erro": "envie um XML da NF-e para importar"}), 400

    try:
        resumo_nfe = _importar_nfe_abastecimento_por_xml_text(
            abastecimento_id,
            xml_text,
            chave_acesso_esperada=chave_acesso_esperada,
            combustivel_tipo=combustivel_tipo,
        )
    except ValueError as exc:
        msg = str(exc)
        status_code = 404 if "nao encontrado" in msg else (409 if "somente" in msg.lower() or "ja cadastrada" in msg.lower() else 400)
        return jsonify({"erro": msg}), status_code

    chave_xml = _normalizar_chave_acesso_nfe(resumo_nfe.get("chave_acesso_nfe"))

    return jsonify({
        "ok": True,
        "id": abastecimento_id,
        "status": "abastecido",
        "combustivel_tipo": _normalizar_combustivel_tipo(resumo_nfe.get("combustivel_tipo")),
        "numero_nota": _as_str(resumo_nfe.get("numero_nota")),
        "chave_acesso_nfe": chave_xml,
        "emitente_nome": _as_str(resumo_nfe.get("emitente_nome")),
        "valor": _as_float(resumo_nfe.get("valor"), 0.0),
        "quantidade_litros": _as_float(resumo_nfe.get("quantidade_litros"), 0.0),
        "itens_encontrados": _as_int(resumo_nfe.get("itens_encontrados"), 0),
    })

@app.route("/api/abastecimentos/<int:abastecimento_id>/importar_nfe_dfe", methods=["POST"])
def importar_nfe_dfe_abastecimento(abastecimento_id):
    payload = request.get_json(silent=True) or {}
    chave_acesso_esperada = _normalizar_chave_acesso_nfe(payload.get("chave_acesso_esperada") or payload.get("chave_acesso"))
    combustivel_tipo = payload.get("combustivel_tipo")
    manifestar_automaticamente = payload.get("manifestar_automaticamente")

    if len(chave_acesso_esperada) != 44:
        return jsonify({"erro": "a chave de acesso da NF-e precisa ter 44 digitos."}), 400

    try:
        resultado_dfe = _buscar_xml_nfe_por_chave_df_e(
            chave_acesso_esperada,
            manifestar_automaticamente=manifestar_automaticamente,
        )
        resumo_nfe = _importar_nfe_abastecimento_por_xml_text(
            abastecimento_id,
            resultado_dfe.get("xml_text"),
            chave_acesso_esperada=chave_acesso_esperada,
            combustivel_tipo=combustivel_tipo,
        )
    except ValueError as exc:
        msg = str(exc)
        status_code = 404 if "nao encontrado" in msg else (409 if "somente" in msg.lower() or "ja cadastrada" in msg.lower() else 400)
        return jsonify({"erro": msg}), status_code

    return jsonify({
        "ok": True,
        "id": abastecimento_id,
        "status": "abastecido",
        "combustivel_tipo": _normalizar_combustivel_tipo(resumo_nfe.get("combustivel_tipo")),
        "numero_nota": _as_str(resumo_nfe.get("numero_nota")),
        "chave_acesso_nfe": _normalizar_chave_acesso_nfe(resumo_nfe.get("chave_acesso_nfe")),
        "emitente_nome": _as_str(resumo_nfe.get("emitente_nome")),
        "valor": _as_float(resumo_nfe.get("valor"), 0.0),
        "quantidade_litros": _as_float(resumo_nfe.get("quantidade_litros"), 0.0),
        "itens_encontrados": _as_int(resumo_nfe.get("itens_encontrados"), 0),
        "dfe": _nfe_resumo_distribuicao_publico(resultado_dfe),
    })

@app.route("/api/abastecimentos/<int:abastecimento_id>", methods=["DELETE"])
def excluir_abastecimento(abastecimento_id):
    usuario = _usuario_ator_req()
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT
                a.id,
                a.veiculo_id,
                a.km,
                a.posto,
                a.combustivel_tipo,
                a.numero_nota,
                a.emitente_nome,
                a.valor,
                a.quantidade_litros,
                a.status,
                v.nome AS veiculo_nome,
                v.placa,
                v.modelo
            FROM abastecimentos a
            LEFT JOIN veiculos v ON v.id = a.veiculo_id
            WHERE a.id=%s
        """, (abastecimento_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"erro": "abastecimento nao encontrado"}), 404

        cur.execute("DELETE FROM abastecimentos WHERE id=%s", (abastecimento_id,))
        veiculo_label = " / ".join([
            item for item in [
                _as_str(row.get("veiculo_nome")),
                _as_str(row.get("placa")),
                _as_str(row.get("modelo")),
            ] if item
        ]) or f"veiculo_id={_as_int(row.get('veiculo_id'), 0)}"
        descricao = (
            f"abastecimento id={abastecimento_id} veiculo={veiculo_label} "
            f"km={_as_int(row.get('km'), 0)} posto={_as_str(row.get('posto'))} "
            f"combustivel={_normalizar_combustivel_tipo(row.get('combustivel_tipo'))} "
            f"nota={_as_str(row.get('numero_nota'))} emitente={_as_str(row.get('emitente_nome'))} "
            f"valor={_as_float(row.get('valor'), 0.0)} qtd={_as_float(row.get('quantidade_litros'), 0.0)} "
            f"status={_as_str(row.get('status'))}"
        )
        _registrar_log_exclusao(cur, usuario, "abastecimentos", abastecimento_id, descricao)
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return jsonify({"ok": True, "id": abastecimento_id})

@app.route("/api/abastecimentos/<int:abastecimento_id>/pdf", methods=["GET"])
def pdf_abastecimento(abastecimento_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            a.*,
            v.nome AS veiculo_nome,
            v.placa,
            v.modelo
        FROM abastecimentos a
        LEFT JOIN veiculos v ON v.id = a.veiculo_id
        WHERE a.id = %s
    """, (abastecimento_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({"erro": "requisição não encontrada"}), 404

    arquivo = _build_abastecimento_pdf(row)
    return send_file(arquivo, as_attachment=False, mimetype="application/pdf")

@app.route("/api/manutencoes", methods=["POST"])
def criar_manutencao():
    data = request.json or {}
    veiculo_id = _as_int(data.get("veiculo_id"), 0)
    if veiculo_id <= 0:
        return jsonify({"erro": "veiculo_id inválido"}), 400

    tipo = _as_str(data.get("tipo"))
    km = _as_int(data.get("km"), 0)
    valor = data.get("valor")
    try:
        valor = float(valor) if valor is not None and str(valor).strip() != "" else 0.0
    except:
        valor = 0.0

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO manutencoes (veiculo_id, tipo, km, valor) VALUES (%s,%s,%s,%s)",
        (veiculo_id, tipo, km, valor)
    )
    if km > 0:
        cur.execute(
            """
            UPDATE veiculos
            SET km_atual = CASE
                WHEN km_atual IS NULL OR km_atual < %s THEN %s
                ELSE km_atual
            END
            WHERE id = %s
            """,
            (km, km, veiculo_id)
        )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/manutencoes", methods=["GET"])
def listar_manutencoes():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            m.id,
            m.veiculo_id,
            m.tipo,
            m.km,
            m.valor,
            m.data_registro,
            v.nome AS veiculo_nome,
            v.placa,
            v.modelo
        FROM manutencoes m
        LEFT JOIN veiculos v ON v.id = m.veiculo_id
        ORDER BY m.id DESC
    """)
    rows = cur.fetchall() or []
    cur.close()
    conn.close()
    return jsonify([
        {
            "id": _as_int(r.get("id"), 0),
            "veiculo_id": _as_int(r.get("veiculo_id"), 0),
            "veiculo_nome": _as_str(r.get("veiculo_nome")),
            "placa": _as_str(r.get("placa")),
            "modelo": _as_str(r.get("modelo")),
            "tipo": _as_str(r.get("tipo")),
            "km": _as_int(r.get("km"), 0),
            "valor": _as_float(r.get("valor"), 0.0),
            "data_registro": _fmt_dt(r.get("data_registro")),
        } for r in rows
    ])

@app.route("/api/trocas_oleo", methods=["POST"])
def criar_troca_oleo():
    data = request.json or {}
    veiculo_id = _as_int(data.get("veiculo_id"), 0)
    if veiculo_id <= 0:
        return jsonify({"erro": "veiculo_id inválido"}), 400

    tipo = _as_str(data.get("tipo"))
    km = _as_int(data.get("km"), 0)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO trocas_oleo (veiculo_id, tipo, km) VALUES (%s,%s,%s)",
        (veiculo_id, tipo, km)
    )
    if km > 0:
        cur.execute(
            """
            UPDATE veiculos
            SET km_atual = CASE
                WHEN km_atual IS NULL OR km_atual < %s THEN %s
                ELSE km_atual
            END
            WHERE id = %s
            """,
            (km, km, veiculo_id)
        )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/trocas_oleo", methods=["GET"])
def listar_trocas_oleo():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            o.id,
            o.veiculo_id,
            o.tipo,
            o.km,
            o.data_registro,
            v.nome AS veiculo_nome,
            v.placa,
            v.modelo
        FROM trocas_oleo o
        LEFT JOIN veiculos v ON v.id = o.veiculo_id
        ORDER BY o.id DESC
    """)
    rows = cur.fetchall() or []
    cur.close()
    conn.close()
    return jsonify([
        {
            "id": _as_int(r.get("id"), 0),
            "veiculo_id": _as_int(r.get("veiculo_id"), 0),
            "veiculo_nome": _as_str(r.get("veiculo_nome")),
            "placa": _as_str(r.get("placa")),
            "modelo": _as_str(r.get("modelo")),
            "tipo": _as_str(r.get("tipo")),
            "km": _as_int(r.get("km"), 0),
            "data_registro": _fmt_dt(r.get("data_registro")),
        } for r in rows
    ])

@app.route("/api/trocas_pneu", methods=["POST"])
def criar_troca_pneu():
    data = request.json or {}
    veiculo_id = _as_int(data.get("veiculo_id"), 0)
    if veiculo_id <= 0:
        return jsonify({"erro": "veiculo_id inválido"}), 400

    km = _as_int(data.get("km"), 0)
    if km <= 0:
        return jsonify({"erro": "km inválido"}), 400

    marca = _as_str(data.get("marca"))
    if not marca:
        return jsonify({"erro": "marca é obrigatória"}), 400

    data_troca = _as_str(data.get("data_troca"))
    if not data_troca:
        data_troca = datetime.datetime.now().strftime("%Y-%m-%d")

    quantidade = _as_int(data.get("quantidade"), 0)
    if quantidade <= 0:
        return jsonify({"erro": "quantidade inválida"}), 400

    valor_total = _as_float(data.get("valor_total"), 0.0)
    localizacao_posicao = _as_str(data.get("localizacao_posicao"))
    localizacao_lado = _as_str(data.get("localizacao_lado"))
    localizacao = _as_str(data.get("localizacao"))
    if not localizacao:
        localizacao = " ".join([x for x in [localizacao_posicao, localizacao_lado] if x]).strip()
    observacao_rodizio = _as_str(data.get("observacao_rodizio"))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO trocas_pneu
            (veiculo_id, data_troca, km, marca, valor_total, quantidade, localizacao_posicao, localizacao_lado, localizacao, observacao_rodizio)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (veiculo_id, data_troca, km, marca, valor_total, quantidade, localizacao_posicao, localizacao_lado, localizacao, observacao_rodizio)
    )
    cur.execute(
        """
        UPDATE veiculos
        SET km_atual = CASE
            WHEN km_atual IS NULL OR km_atual < %s THEN %s
            ELSE km_atual
        END
        WHERE id = %s
        """,
        (km, km, veiculo_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/lavagens", methods=["POST"])
def criar_lavagem():
    data = request.json or {}
    veiculo_id = _as_int(data.get("veiculo_id"), 0)
    if veiculo_id <= 0:
        return jsonify({"erro": "veiculo_id inválido"}), 400

    km = _as_int(data.get("km"), 0)
    data_lavagem = _as_str(data.get("data_lavagem")) or datetime.datetime.now().strftime("%Y-%m-%d")
    local = _as_str(data.get("local"))
    valor = _as_float(data.get("valor"), 0.0)
    observacao = _as_str(data.get("observacao"))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO lavagens (veiculo_id, data_lavagem, km, local, valor, observacao)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (veiculo_id, data_lavagem, km, local, valor, observacao)
    )
    if km > 0:
        cur.execute(
            """
            UPDATE veiculos
            SET km_atual = CASE
                WHEN km_atual IS NULL OR km_atual < %s THEN %s
                ELSE km_atual
            END
            WHERE id = %s
            """,
            (km, km, veiculo_id)
        )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/lavagens", methods=["GET"])
def listar_lavagens():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            l.id,
            l.veiculo_id,
            l.data_lavagem,
            l.km,
            l.local,
            l.valor,
            l.observacao,
            l.data_registro,
            v.nome AS veiculo_nome,
            v.placa,
            v.modelo
        FROM lavagens l
        LEFT JOIN veiculos v ON v.id = l.veiculo_id
        ORDER BY l.id DESC
    """)
    rows = cur.fetchall() or []
    cur.close()
    conn.close()
    return jsonify([
        {
            "id": _as_int(r.get("id"), 0),
            "veiculo_id": _as_int(r.get("veiculo_id"), 0),
            "veiculo_nome": _as_str(r.get("veiculo_nome")),
            "placa": _as_str(r.get("placa")),
            "modelo": _as_str(r.get("modelo")),
            "data_lavagem": _fmt_dt(r.get("data_lavagem")),
            "km": _as_int(r.get("km"), 0),
            "local": _as_str(r.get("local")),
            "valor": _as_float(r.get("valor"), 0.0),
            "observacao": _as_str(r.get("observacao")),
            "data_registro": _fmt_dt(r.get("data_registro")),
        } for r in rows
    ])

@app.route("/api/trocas_pneu", methods=["GET"])
def listar_trocas_pneu():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            tp.id,
            tp.veiculo_id,
            tp.data_troca,
            tp.km,
            tp.marca,
            tp.valor_total,
            tp.quantidade,
            tp.localizacao_posicao,
            tp.localizacao_lado,
            tp.localizacao,
            tp.observacao_rodizio,
            tp.data_registro,
            v.nome AS veiculo_nome,
            v.placa,
            v.modelo
        FROM trocas_pneu tp
        LEFT JOIN veiculos v ON v.id = tp.veiculo_id
        ORDER BY tp.veiculo_id ASC, tp.km ASC, tp.id ASC
    """)
    rows = cur.fetchall() or []
    cur.close()
    conn.close()

    prev_km_by_veiculo = {}
    metricas = {}
    for r in rows:
        rid = _as_int(r.get("id"), 0)
        vid = _as_int(r.get("veiculo_id"), 0)
        km = _as_int(r.get("km"), 0)
        qtd = _as_int(r.get("quantidade"), 0)
        valor_total = _as_float(r.get("valor_total"), 0.0)

        km_rodado = None
        km_por_pneu = None
        prev_km = prev_km_by_veiculo.get(vid)
        if prev_km is not None:
            dist = km - prev_km
            if dist > 0:
                km_rodado = dist
                if qtd > 0:
                    km_por_pneu = dist / qtd
        prev_km_by_veiculo[vid] = km

        custo_por_pneu = (valor_total / qtd) if qtd > 0 else None
        metricas[rid] = {
            "km_rodado": km_rodado,
            "km_por_pneu": km_por_pneu,
            "custo_por_pneu": custo_por_pneu,
        }

    out = []
    for r in sorted(rows, key=lambda x: _as_int(x.get("id"), 0), reverse=True):
        rid = _as_int(r.get("id"), 0)
        m = metricas.get(rid) or {}
        out.append({
            "id": rid,
            "veiculo_id": _as_int(r.get("veiculo_id"), 0),
            "veiculo_nome": r.get("veiculo_nome") or "",
            "placa": r.get("placa") or "",
            "modelo": r.get("modelo") or "",
            "data_troca": _fmt_dt(r.get("data_troca")),
            "km": _as_int(r.get("km"), 0),
            "marca": _as_str(r.get("marca")),
            "valor_total": _as_float(r.get("valor_total"), 0.0),
            "quantidade": _as_int(r.get("quantidade"), 0),
            "localizacao_posicao": _as_str(r.get("localizacao_posicao")),
            "localizacao_lado": _as_str(r.get("localizacao_lado")),
            "localizacao": _as_str(r.get("localizacao")),
            "observacao_rodizio": _as_str(r.get("observacao_rodizio")),
            "data_registro": _fmt_dt(r.get("data_registro")),
            "km_rodado": m.get("km_rodado"),
            "km_por_pneu": m.get("km_por_pneu"),
            "custo_por_pneu": m.get("custo_por_pneu"),
        })

    return jsonify(out)

@app.route("/api/frota_relatorio", methods=["GET"])
def relatorio_frota_pdf():
    tipo = _as_str(request.args.get("tipo")).lower() or "resumo"
    _limpar_fretes_finalizados_expirados()
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    filtros_frete = _coletar_filtros_relatorio_fretes_req()

    titulo = "Relatório da Frota"
    slug = tipo
    headers = []
    rows = []

    if tipo == "resumo":
        titulo = "Relatório da Frota"
        headers = ["Caminhão", "Placa", "Modelo", "KM Atual", "Ult. Óleo", "Manutenções", "Custo Total", "Falta Manut.", "Falta Óleo"]
        cur.execute("""
            SELECT
                v.id,
                v.nome,
                v.placa,
                v.modelo,
                v.km_atual,
                v.intervalo_manut_km,
                v.intervalo_oleo_km,
                (SELECT o.km FROM trocas_oleo o WHERE o.veiculo_id=v.id ORDER BY o.km DESC, o.id DESC LIMIT 1) AS ultimo_oleo_km,
                (SELECT COUNT(*) FROM manutencoes m WHERE m.veiculo_id=v.id) AS manut_count,
                (SELECT COALESCE(SUM(m.valor),0) FROM manutencoes m WHERE m.veiculo_id=v.id) AS custo_total,
                (SELECT m.km FROM manutencoes m WHERE m.veiculo_id=v.id ORDER BY m.km DESC, m.id DESC LIMIT 1) AS ultima_manut_km
            FROM veiculos v
            ORDER BY v.nome ASC, v.id ASC
        """)
        for r in (cur.fetchall() or []):
            km_atual = _as_int(r.get("km_atual"), 0)
            int_manut = _as_int(r.get("intervalo_manut_km"), 10000)
            int_oleo = _as_int(r.get("intervalo_oleo_km"), 5000)
            ultima_manut = _normalizar_km_base(r.get("ultima_manut_km"), km_atual)
            ultimo_oleo = _normalizar_km_base(r.get("ultimo_oleo_km"), km_atual)
            falta_manut = (ultima_manut + int_manut) - km_atual if int_manut > 0 else 0
            falta_oleo = (ultimo_oleo + int_oleo) - km_atual if int_oleo > 0 else 0
            rows.append([
                r.get("nome") or "-",
                r.get("placa") or "-",
                r.get("modelo") or "-",
                str(km_atual),
                str(ultimo_oleo),
                str(_as_int(r.get("manut_count"), 0)),
                _fmt_money_br(r.get("custo_total")),
                f"{falta_manut} km",
                f"{falta_oleo} km",
            ])
    elif tipo == "manutencoes":
        titulo = "Relatório de Manutenções"
        headers = ["Data", "Caminhão", "Placa", "Modelo", "Tipo", "KM", "Valor"]
        cur.execute("""
            SELECT
                m.data_registro,
                m.tipo,
                m.km,
                m.valor,
                v.nome AS veiculo_nome,
                v.placa,
                v.modelo
            FROM manutencoes m
            LEFT JOIN veiculos v ON v.id = m.veiculo_id
            ORDER BY m.id DESC
        """)
        rows = [[
            _fmt_dt(r.get("data_registro")) or "-",
            r.get("veiculo_nome") or "-",
            r.get("placa") or "-",
            r.get("modelo") or "-",
            r.get("tipo") or "-",
            str(_as_int(r.get("km"), 0)),
            _fmt_money_br(r.get("valor")),
        ] for r in (cur.fetchall() or [])]
    elif tipo == "trocas_oleo":
        titulo = "Relatório de Trocas de Óleo"
        headers = ["Data", "Caminhão", "Placa", "Modelo", "Tipo", "KM"]
        cur.execute("""
            SELECT
                o.data_registro,
                o.tipo,
                o.km,
                v.nome AS veiculo_nome,
                v.placa,
                v.modelo
            FROM trocas_oleo o
            LEFT JOIN veiculos v ON v.id = o.veiculo_id
            ORDER BY o.id DESC
        """)
        rows = [[
            _fmt_dt(r.get("data_registro")) or "-",
            r.get("veiculo_nome") or "-",
            r.get("placa") or "-",
            r.get("modelo") or "-",
            r.get("tipo") or "-",
            str(_as_int(r.get("km"), 0)),
        ] for r in (cur.fetchall() or [])]
    elif tipo == "trocas_pneu":
        titulo = "Relatório de Trocas de Pneu"
        headers = ["Data", "Caminhão", "Placa", "Marca", "KM", "Qtd", "Valor", "Localização"]
        cur.execute("""
            SELECT
                tp.data_troca,
                tp.km,
                tp.marca,
                tp.quantidade,
                tp.valor_total,
                tp.localizacao,
                v.nome AS veiculo_nome,
                v.placa
            FROM trocas_pneu tp
            LEFT JOIN veiculos v ON v.id = tp.veiculo_id
            ORDER BY tp.id DESC
        """)
        rows = [[
            _fmt_dt(r.get("data_troca")) or "-",
            r.get("veiculo_nome") or "-",
            r.get("placa") or "-",
            r.get("marca") or "-",
            str(_as_int(r.get("km"), 0)),
            str(_as_int(r.get("quantidade"), 0)),
            _fmt_money_br(r.get("valor_total")),
            r.get("localizacao") or "-",
        ] for r in (cur.fetchall() or [])]
    elif tipo == "abastecimentos":
        titulo = "Relatório de Abastecimentos"
        headers = ["Data", "Caminhao", "Placa", "Combustivel", "KM", "Posto", "NF-e", "Qtd", "Valor", "Status"]
        cur.execute("""
            SELECT
                COALESCE(a.data_abastecimento, a.data_liberacao) AS data_evento,
                a.km,
                a.posto,
                a.combustivel_tipo,
                a.numero_nota,
                a.quantidade_litros,
                a.valor,
                a.status,
                v.nome AS veiculo_nome,
                v.placa
            FROM abastecimentos a
            LEFT JOIN veiculos v ON v.id = a.veiculo_id
            ORDER BY a.id DESC
        """)
        rows = [[
            _fmt_dt(r.get("data_evento")) or "-",
            r.get("veiculo_nome") or "-",
            r.get("placa") or "-",
            _combustivel_tipo_label(r.get("combustivel_tipo")),
            str(_as_int(r.get("km"), 0)),
            r.get("posto") or "-",
            r.get("numero_nota") or "-",
            str(_as_float(r.get("quantidade_litros"), 0.0)),
            _fmt_money_br(r.get("valor")),
            r.get("status") or "-",
        ] for r in (cur.fetchall() or [])]
    elif tipo == "lavagens":
        titulo = "Relatório de Lavagens"
        headers = ["Data", "Caminhão", "Placa", "KM", "Local", "Valor", "Observação"]
        cur.execute("""
            SELECT
                l.data_lavagem,
                l.km,
                l.local,
                l.valor,
                l.observacao,
                v.nome AS veiculo_nome,
                v.placa
            FROM lavagens l
            LEFT JOIN veiculos v ON v.id = l.veiculo_id
            ORDER BY l.id DESC
        """)
        rows = [[
            _fmt_dt(r.get("data_lavagem")) or "-",
            r.get("veiculo_nome") or "-",
            r.get("placa") or "-",
            str(_as_int(r.get("km"), 0)),
            r.get("local") or "-",
            _fmt_money_br(r.get("valor")),
            r.get("observacao") or "-",
        ] for r in (cur.fetchall() or [])]
    elif tipo == "escala":
        titulo = "Relatorio de Escala"
        headers, rows = _dados_relatorio_escala(cur, filtros_frete)
    elif tipo == "historico_fretes":
        titulo = "Relatorio de Historico de Fretes"
        headers = ["Data", "Acao", "Frete", "Status ant.", "Status novo", "Veiculo", "Motorista", "Entregador", "Usuario", "Detalhes"]
        where = []
        params = []
        if filtros_frete.get("data_inicio"):
            where.append("DATE(fh.criado_em) >= %s")
            params.append(filtros_frete["data_inicio"])
        if filtros_frete.get("data_fim"):
            where.append("DATE(fh.criado_em) <= %s")
            params.append(filtros_frete["data_fim"])
        status_list = filtros_frete.get("status_list") or []
        if status_list:
            placeholders = ", ".join(["%s"] * len(status_list))
            where.append(f"(fh.status_anterior IN ({placeholders}) OR fh.status_novo IN ({placeholders}))")
            params.extend(status_list)
            params.extend(status_list)

        sql = """
            SELECT
                fh.criado_em,
                fh.acao,
                fh.frete_nome,
                fh.status_anterior,
                fh.status_novo,
                fh.veiculo_nome,
                fh.motorista_nome,
                fh.entregador_nome,
                fh.usuario,
                fh.detalhes
            FROM fretes_historico fh
        """
        if where:
            sql += "\nWHERE " + " AND ".join(where)
        sql += "\nORDER BY fh.id DESC"
        cur.execute(sql, params)
        rows = [[
            _fmt_dt(r.get("criado_em")) or "-",
            r.get("acao") or "-",
            r.get("frete_nome") or "-",
            r.get("status_anterior") or "-",
            r.get("status_novo") or "-",
            r.get("veiculo_nome") or "-",
            r.get("motorista_nome") or "-",
            r.get("entregador_nome") or "-",
            r.get("usuario") or "-",
            r.get("detalhes") or "-",
        ] for r in (cur.fetchall() or [])]
    else:
        cur.close()
        conn.close()
        return jsonify({"erro": "tipo de relatório inválido"}), 400

    cur.close()
    conn.close()

    filtros_pdf = None
    if tipo == "escala":
        filtros_pdf = list(filtros_frete.get("resumo") or [])
        filtros_pdf.append("Ordenacao: " + RELATORIO_ESCALA_ORDENACAO[filtros_frete.get("ordenacao") or "status_data"]["label"])
    elif tipo == "historico_fretes":
        filtros_pdf = filtros_frete.get("resumo")
    arquivo = _build_frota_report_pdf(titulo, headers, rows, slug, filtros_pdf)
    return send_file(
        arquivo,
        as_attachment=False,
        download_name=f"{slug}.pdf",
        mimetype="application/pdf"
    )

@app.route("/api/frota_resumo", methods=["GET"])
def frota_resumo():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    # Última troca de óleo e total de manutenções/custos
    cur.execute("""
    SELECT
      v.id,
      v.nome,
      v.placa,
      v.modelo,
      v.km_atual,
      v.intervalo_manut_km,
      v.intervalo_oleo_km,
      (SELECT o.km FROM trocas_oleo o WHERE o.veiculo_id=v.id ORDER BY o.km DESC, o.id DESC LIMIT 1) AS ultimo_oleo_km,
      (SELECT COUNT(*) FROM manutencoes m WHERE m.veiculo_id=v.id) AS manut_count,
      (SELECT COALESCE(SUM(m.valor),0) FROM manutencoes m WHERE m.veiculo_id=v.id) AS custo_total,
      (SELECT m.km FROM manutencoes m WHERE m.veiculo_id=v.id ORDER BY m.km DESC, m.id DESC LIMIT 1) AS ultima_manut_km
    FROM veiculos v
    ORDER BY v.id DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # Calcular faltas
    out = []
    for r in rows:
        km_atual = _as_int(r.get("km_atual"), 0)
        int_manut = _as_int(r.get("intervalo_manut_km"), 10000)
        int_oleo = _as_int(r.get("intervalo_oleo_km"), 5000)
        ultima_manut = _normalizar_km_base(r.get("ultima_manut_km"), km_atual)
        ultimo_oleo = _normalizar_km_base(r.get("ultimo_oleo_km"), km_atual)

        falta_manut = (ultima_manut + int_manut) - km_atual if int_manut > 0 else 0
        falta_oleo = (ultimo_oleo + int_oleo) - km_atual if int_oleo > 0 else 0

        r["falta_manut_km"] = falta_manut
        r["falta_oleo_km"] = falta_oleo
        out.append(r)

    return jsonify(out)

@app.route("/api/dashboard_frota", methods=["GET"])
def dashboard_frota():
    """Dashboard 2 - tabela Frota/Manutenção.
    Compatível com MySQL/MariaDB sem window functions.
    """
    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    # Veículos (base)
    cur.execute("""
        SELECT id, nome, placa, modelo, km_atual, intervalo_manut_km, intervalo_oleo_km
        FROM veiculos
        ORDER BY id DESC
    """)
    veiculos = cur.fetchall() or []

    # Descobre se existem tabelas necessárias (fretes/motoristas)
    def table_exists(name):
        try:
            cur.execute("SHOW TABLES LIKE %s", (name,))
            return cur.fetchone() is not None
        except Exception:
            return False

    has_fretes = table_exists("fretes")
    has_motoristas = table_exists("motoristas")

    frete_por_veiculo = {}
    if has_fretes:
        # último frete por veículo (por id mais alto)
        try:
            cur.execute("""
                SELECT f1.*
                FROM fretes f1
                INNER JOIN (
                    SELECT veiculo_id, MAX(id) AS max_id
                    FROM fretes
                    GROUP BY veiculo_id
                ) x ON x.veiculo_id = f1.veiculo_id AND x.max_id = f1.id
            """)
            for f in (cur.fetchall() or []):
                frete_por_veiculo[int(f.get("veiculo_id") or 0)] = f
        except Exception:
            frete_por_veiculo = {}

    motorista_nome = {}
    if has_motoristas and frete_por_veiculo:
        ids = sorted({int(f.get("motorista_id") or 0) for f in frete_por_veiculo.values() if f.get("motorista_id")})
        if ids:
            try:
                cur.execute(
                    "SELECT id, nome FROM motoristas WHERE id IN (" + ",".join(["%s"]*len(ids)) + ")",
                    tuple(ids)
                )
                for m in (cur.fetchall() or []):
                    motorista_nome[int(m["id"])] = m.get("nome") or ""
            except Exception:
                pass

    # Últimos KM de óleo / manutenção e média KM/L baseada no histórico de abastecimento
    ultimo_oleo = {}
    ultimo_oleo_tipo = {}
    ultima_manut = {}
    ultima_manut_tipo = {}
    media_km_l = {}

    # Trocas de óleo
    try:
        cur.execute("SELECT veiculo_id, km, tipo FROM trocas_oleo ORDER BY veiculo_id, km DESC, id DESC")
        rows = cur.fetchall() or []
        # agrupa por veículo (mantendo lista desc)
        by = {}
        by_tipo = {}
        for r in rows:
            vid = int(r.get("veiculo_id") or 0)
            by.setdefault(vid, []).append(int(r.get("km") or 0))
            # guarda tipos na mesma ordem
            by_tipo.setdefault(vid, []).append((r.get("tipo") or ""))
        for vid, kms_desc in by.items():
            if kms_desc:
                ultimo_oleo[vid] = kms_desc[0]
                # tipo do último óleo
                try:
                    ultimo_oleo_tipo[vid] = (by_tipo.get(vid) or [''])[0]
                except Exception:
                    pass
    except Exception:
        pass

    # Manutenções
    try:
        cur.execute("SELECT veiculo_id, km, tipo FROM manutencoes ORDER BY veiculo_id, km DESC, id DESC")
        rows = cur.fetchall() or []
        for r in rows:
            vid = int(r.get("veiculo_id") or 0)
            if vid not in ultima_manut:
                ultima_manut[vid] = int(r.get("km") or 0)
                ultima_manut_tipo[vid] = (r.get("tipo") or "")
    except Exception:
        pass

    # Abastecimentos: calcula média KM/L do histórico por veículo.
    # Regra: para cada abastecimento concluído, usa distância desde o abastecimento anterior
    # e divide pela quantidade abastecida no abastecimento atual.
    try:
        cur.execute("""
            SELECT veiculo_id, km, quantidade_litros, combustivel_tipo
            FROM abastecimentos
            WHERE status = 'abastecido'
            ORDER BY veiculo_id ASC, km ASC, id ASC
        """)
        rows = cur.fetchall() or []
        by = {}
        for r in rows:
            vid = _as_int(r.get("veiculo_id"), 0)
            if _normalizar_combustivel_tipo(r.get("combustivel_tipo")) != "diesel":
                continue
            by.setdefault(vid, []).append({
                "km": _as_int(r.get("km"), 0),
                "litros": _as_float(r.get("quantidade_litros"), 0.0),
            })

        for vid, seq in by.items():
            metricas = []
            prev_km = None
            for item in seq:
                km_atual = item["km"]
                litros = item["litros"]
                if prev_km is not None:
                    dist = km_atual - prev_km
                    if dist > 0 and litros > 0:
                        metricas.append(dist / litros)
                prev_km = km_atual
            if metricas:
                # Usa apenas a última medição válida de KM/L
                media_km_l[vid] = metricas[-1]
    except Exception:
        pass

    cur.close()
    conn.close()

    out = []
    for v in veiculos:
        vid = int(v.get("id") or 0)
        km_atual = _as_int(v.get("km_atual"), 0)
        int_manut = _as_int(v.get("intervalo_manut_km"), 10000)
        int_oleo = _as_int(v.get("intervalo_oleo_km"), 5000)

        u_manut = _normalizar_km_base(ultima_manut.get(vid), km_atual)
        u_oleo = _normalizar_km_base(ultimo_oleo.get(vid), km_atual)

        falta_manut = (u_manut + int_manut) - km_atual if int_manut > 0 else 0
        falta_oleo = (u_oleo + int_oleo) - km_atual if int_oleo > 0 else 0

        f = frete_por_veiculo.get(vid) or {}
        mid = _as_int(f.get("motorista_id"), 0)
        row = {
            "veiculo_id": vid,
            "veiculo_nome": v.get("nome") or "",
            "placa": v.get("placa") or "",
            "modelo": v.get("modelo") or "",
            "km_atual": km_atual,
            "intervalo_manut_km": int_manut,
            "intervalo_oleo_km": int_oleo,
            "frete_id": f.get("id"),
            "frete_nome": f.get("nome") or f.get("descricao") or "",
            "frete_status": f.get("status") or "",
            "motorista_nome": motorista_nome.get(mid) or "",
            "ultimo_oleo_km": u_oleo,
            "ultima_manut_km": u_manut,
            "media_km": media_km_l.get(vid),
            "falta_manut_km": falta_manut,
            "falta_oleo_km": falta_oleo,
            "alerta": True if (falta_manut <= 0 or falta_oleo <= 0) else False
        }
        out.append(row)

    return jsonify(out)

@app.route("/api/frota_historico/<int:veiculo_id>", methods=["GET"])
def frota_historico(veiculo_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT id, nome, placa, modelo, km_atual, intervalo_manut_km, intervalo_oleo_km
        FROM veiculos
        WHERE id = %s
        LIMIT 1
    """, (veiculo_id,))
    veiculo = cur.fetchone()
    if not veiculo:
        cur.close()
        conn.close()
        return jsonify({"erro": "Veiculo nao encontrado"}), 404

    try:
        cur.execute("""
            SELECT
                f.id,
                f.nome,
                f.status,
                f.observacao,
                f.motorista_id,
                f.entregador_id,
                f.km_atual,
                f.peso,
                f.qtd_entregas,
                m.nome AS motorista_nome,
                e.nome AS entregador_nome,
                c.nome AS carga_nome
            FROM fretes f
            LEFT JOIN motoristas m ON m.id = f.motorista_id
            LEFT JOIN motoristas e ON e.id = f.entregador_id
            LEFT JOIN cargas c ON c.id = f.carga_id
            WHERE f.veiculo_id = %s
            ORDER BY f.id DESC
            LIMIT 1
        """, (veiculo_id,))
        frete = cur.fetchone() or {}
    except Exception:
        frete = {}

    cur.execute("""
        SELECT id, tipo, km, valor, data_registro
        FROM manutencoes
        WHERE veiculo_id = %s
        ORDER BY km DESC, id DESC
    """, (veiculo_id,))
    manutencoes = cur.fetchall() or []

    cur.execute("""
        SELECT id, tipo, km, data_registro
        FROM trocas_oleo
        WHERE veiculo_id = %s
        ORDER BY km DESC, id DESC
    """, (veiculo_id,))
    trocas_oleo = cur.fetchall() or []

    cur.execute("""
        SELECT
            id,
            data_troca,
            km,
            marca,
            valor_total,
            quantidade,
            localizacao,
            observacao_rodizio,
            data_registro
        FROM trocas_pneu
        WHERE veiculo_id = %s
        ORDER BY km DESC, id DESC
    """, (veiculo_id,))
    trocas_pneu = cur.fetchall() or []

    cur.execute("""
        SELECT
            id,
            km,
            posto,
            combustivel_tipo,
            chave_acesso_nfe,
            numero_nota,
            emitente_nome,
            valor,
            quantidade_litros,
            status,
            data_liberacao,
            data_abastecimento
        FROM abastecimentos
        WHERE veiculo_id = %s
        ORDER BY km ASC, id ASC
    """, (veiculo_id,))
    abastecimentos = cur.fetchall() or []

    cur.execute("""
        SELECT
            id,
            data_lavagem,
            km,
            local,
            valor,
            observacao,
            data_registro
        FROM lavagens
        WHERE veiculo_id = %s
        ORDER BY km DESC, id DESC
    """, (veiculo_id,))
    lavagens = cur.fetchall() or []

    cur.close()
    conn.close()

    km_atual = _as_int(veiculo.get("km_atual"), 0)
    int_manut = _as_int(veiculo.get("intervalo_manut_km"), 10000)
    int_oleo = _as_int(veiculo.get("intervalo_oleo_km"), 5000)
    ultima_manut_km = _normalizar_km_base((manutencoes[0] or {}).get("km"), km_atual) if manutencoes else km_atual
    ultimo_oleo_km = _normalizar_km_base((trocas_oleo[0] or {}).get("km"), km_atual) if trocas_oleo else km_atual

    falta_manut = (ultima_manut_km + int_manut) - km_atual if int_manut > 0 else 0
    falta_oleo = (ultimo_oleo_km + int_oleo) - km_atual if int_oleo > 0 else 0

    medias_validas = []
    prev_km_abast = None
    for ab in abastecimentos:
        if _as_str(ab.get("status")).lower() != "abastecido":
            continue
        if _normalizar_combustivel_tipo(ab.get("combustivel_tipo")) != "diesel":
            continue
        km = _as_int(ab.get("km"), 0)
        qtd = _as_float(ab.get("quantidade_litros"), 0.0)
        km_l = 0.0
        if prev_km_abast is not None and km > prev_km_abast and qtd > 0:
            km_l = (km - prev_km_abast) / qtd
        prev_km_abast = km
        if km_l > 0:
            medias_validas.append(km_l)
    medias_validas = medias_validas[:6]
    media_km = (sum(medias_validas) / len(medias_validas)) if medias_validas else None

    out = {
        "veiculo": {
            "id": _as_int(veiculo.get("id"), 0),
            "nome": _as_str(veiculo.get("nome")),
            "placa": _as_str(veiculo.get("placa")),
            "modelo": _as_str(veiculo.get("modelo")),
            "km_atual": km_atual,
            "intervalo_manut_km": int_manut,
            "intervalo_oleo_km": int_oleo,
        },
        "frete_atual": {
            "id": frete.get("id"),
            "nome": _as_str(frete.get("nome")),
            "status": _as_str(frete.get("status")),
            "observacao": _as_str(frete.get("observacao")),
            "motorista_nome": _as_str(frete.get("motorista_nome")),
            "entregador_nome": _as_str(frete.get("entregador_nome")),
            "carga_nome": _as_str(frete.get("carga_nome")),
            "km_atual": _as_int(frete.get("km_atual"), 0),
            "peso": _as_float(frete.get("peso"), 0.0),
            "qtd_entregas": _as_int(frete.get("qtd_entregas"), 0),
        },
        "resumo": {
            "km_atual": km_atual,
            "media_km": media_km,
            "ultima_manut_km": (ultima_manut_km if ultima_manut_km > 0 else None),
            "ultimo_oleo_km": (ultimo_oleo_km if ultimo_oleo_km > 0 else None),
            "falta_manut_km": falta_manut,
            "falta_oleo_km": falta_oleo,
            "manut_count": len(manutencoes),
            "manut_custo_total": sum([_as_float(m.get("valor"), 0.0) for m in manutencoes]),
            "trocas_oleo_count": len(trocas_oleo),
            "trocas_pneu_count": len(trocas_pneu),
            "abastecimentos_count": len(abastecimentos),
            "lavagens_count": len(lavagens),
        },
        "historico": {
            "manutencoes": [
                {
                    "id": _as_int(m.get("id"), 0),
                    "tipo": _as_str(m.get("tipo")),
                    "km": _as_int(m.get("km"), 0),
                    "valor": _as_float(m.get("valor"), 0.0),
                    "data_manutencao": _fmt_dt(m.get("data_registro")),
                } for m in manutencoes
            ],
            "trocas_oleo": [
                {
                    "id": _as_int(o.get("id"), 0),
                    "tipo": _as_str(o.get("tipo")),
                    "km": _as_int(o.get("km"), 0),
                    "data_troca": _fmt_dt(o.get("data_registro")),
                } for o in trocas_oleo
            ],
            "trocas_pneu": [
                {
                    "id": _as_int(tp.get("id"), 0),
                    "data_troca": _fmt_dt(tp.get("data_troca")),
                    "data_registro": _fmt_dt(tp.get("data_registro")),
                    "km": _as_int(tp.get("km"), 0),
                    "marca": _as_str(tp.get("marca")),
                    "valor_total": _as_float(tp.get("valor_total"), 0.0),
                    "quantidade": _as_int(tp.get("quantidade"), 0),
                    "localizacao": _as_str(tp.get("localizacao")),
                    "observacao_rodizio": _as_str(tp.get("observacao_rodizio")),
                    "custo_por_pneu": (
                        (_as_float(tp.get("valor_total"), 0.0) / _as_int(tp.get("quantidade"), 0))
                        if _as_int(tp.get("quantidade"), 0) > 0 else None
                    ),
                } for tp in trocas_pneu
            ],
            "abastecimentos": [],
            "lavagens": [
                {
                    "id": _as_int(l.get("id"), 0),
                    "data_lavagem": _fmt_dt(l.get("data_lavagem")),
                    "data_registro": _fmt_dt(l.get("data_registro")),
                    "km": _as_int(l.get("km"), 0),
                    "local": _as_str(l.get("local")),
                    "valor": _as_float(l.get("valor"), 0.0),
                    "observacao": _as_str(l.get("observacao")),
                } for l in lavagens
            ],
        }
    }

    prev_km_abast = None
    for a in abastecimentos:
        km = _as_int(a.get("km"), 0)
        qtd = _as_float(a.get("quantidade_litros"), 0.0)
        status = _as_str(a.get("status"))
        km_l = None
        if status.lower() == "abastecido" and _normalizar_combustivel_tipo(a.get("combustivel_tipo")) == "diesel":
            if prev_km_abast is not None and km > prev_km_abast and qtd > 0:
                km_l = (km - prev_km_abast) / qtd
            prev_km_abast = km
        out["historico"]["abastecimentos"].append({
            "id": _as_int(a.get("id"), 0),
            "km": km,
            "posto": _as_str(a.get("posto")),
            "combustivel_tipo": _normalizar_combustivel_tipo(a.get("combustivel_tipo")),
            "chave_acesso_nfe": _normalizar_chave_acesso_nfe(a.get("chave_acesso_nfe")),
            "numero_nota": _as_str(a.get("numero_nota")),
            "emitente_nome": _as_str(a.get("emitente_nome")),
            "valor": _as_float(a.get("valor"), 0.0),
            "quantidade_litros": _as_float(a.get("quantidade_litros"), 0.0),
            "status": status,
            "data_liberacao": _fmt_dt(a.get("data_liberacao")),
            "data_abastecimento": _fmt_dt(a.get("data_abastecimento")),
            "km_l": km_l,
        })

    out["historico"]["abastecimentos"].sort(key=lambda x: x.get("id", 0), reverse=True)

    return jsonify(out)

# =========================================================
# (8) SERVIR HTML/ARQUIVOS
# =========================================================
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "RioBranco.html")

@app.route("/docs")
@app.route("/docs/")
def docs_index():
    return send_from_directory(DOCS_DIR, "index.html")

@app.route("/docs/<path:filename>")
def docs_files(filename):
    return send_from_directory(DOCS_DIR, filename)

@app.route("/monitor/esxi/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/monitor/esxi/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def monitor_esxi_proxy(subpath):
    return _proxy_monitor("esxi", subpath)

@app.route("/monitor/cameras/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/monitor/cameras/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def monitor_cameras_proxy(subpath):
    return _proxy_monitor("cameras", subpath)

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(BASE_DIR, path)

if __name__ == "__main__":
    host = os.environ.get("APP_HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("APP_PORT", "8443"))
    except Exception:
        port = 8443

    https_enabled = os.environ.get("APP_HTTPS", "1").strip().lower() not in ("0", "false", "no")
    cert_file = os.environ.get("APP_SSL_CERT", "").strip()
    key_file = os.environ.get("APP_SSL_KEY", "").strip()

    ssl_context = None
    if https_enabled:
        if cert_file and key_file:
            ssl_context = (cert_file, key_file)
        else:
            ssl_context = "adhoc"

    app.run(host=host, port=port, ssl_context=ssl_context, threaded=True)
