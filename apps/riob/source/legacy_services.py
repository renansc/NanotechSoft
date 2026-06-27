import csv
import email
import hashlib
import html
import imaplib
import io
import json
import os
import poplib
import re
import shutil
import sqlite3
import threading
import time
import unicodedata
import uuid
import zipfile
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_file,
    url_for,
)
from werkzeug.utils import secure_filename

from ImportarXml.importador_xml_homologacao import (
    classificar_estoque,
    eh_combustivel,
    extrair_abastecimento,
    fmt_cnpj,
    parse_nfe,
    so_num,
)


XML_BP = Blueprint("importar_xml", __name__, url_prefix="/importar-xml")
EMAIL_BP = Blueprint("gestor_emails", __name__, url_prefix="/gestor-emails")

_conn_factory = None
_xml_upload_dir = None
_email_attachment_dir = None
_legacy_xml_root = None
_legacy_email_root = None
_abastecimento_import_callback = None

XML_PROGRESS = {}
XML_PROGRESS_LOCK = threading.Lock()
EMAIL_STATUS = {
    "running": False,
    "total": 0,
    "processed": 0,
    "imported": 0,
    "recovered": 0,
    "attachments": 0,
    "xml_imported": 0,
    "xml_existing": 0,
    "xml_errors": 0,
    "fetch_errors": 0,
    "deleted": 0,
    "scheduler_active": False,
    "scheduler_last_run": "",
    "scheduler_next_run": "",
    "message": "Aguardando importacao...",
}
EMAIL_STATUS_LOCK = threading.Lock()
EMAIL_SCHEDULER_LOCK = threading.Lock()
EMAIL_SCHEDULER_STARTED = False


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _conn():
    if _conn_factory is None:
        raise RuntimeError("Servicos legados ainda nao foram configurados.")
    return _conn_factory()


def _rows(query, params=()):
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(query, params)
        return cur.fetchall()
    finally:
        conn.close()


def _row(query, params=()):
    rows = _rows(query, params)
    return rows[0] if rows else None


def _execute(query, params=()):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _env_bool(name, default="0"):
    value = str(os.environ.get(name, default)).strip().lower()
    return 0 if value in {"0", "false", "nao", "no", "off", "disabled"} else 1


def _seed_env_email_accounts(cur):
    bol_user = str(os.environ.get("RB_EMAIL_BOL_USER", "")).strip()
    bol_pass = os.environ.get("RB_EMAIL_BOL_PASS", "")
    if not bol_user or not bol_pass:
        return

    keywords = os.environ.get(
        "RB_EMAIL_BOL_FILTER_KEYWORDS",
        (
            "compra,compras,cotacao,pedido,materia prima,materia-prima,"
            "insumo,fornecedor,nfe,nf-e,xml"
        ),
    )
    account_id = int(os.environ.get("RB_EMAIL_BOL_ACCOUNT_ID", "2"))
    cur.execute(
        """
        INSERT INTO gestor_email_config (
            id, account_name, protocol, enabled, pop_host, pop_port, use_ssl,
            mailbox, email_user, email_pass, smtp_host, smtp_port, smtp_use_tls,
            since_date, filter_keywords, storage_limit_gb, delete_from_server
        )
        VALUES (%s, %s, 'imap', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, 0)
        ON DUPLICATE KEY UPDATE
            account_name=VALUES(account_name),
            protocol=VALUES(protocol),
            enabled=VALUES(enabled),
            pop_host=VALUES(pop_host),
            pop_port=VALUES(pop_port),
            use_ssl=VALUES(use_ssl),
            mailbox=VALUES(mailbox),
            email_user=VALUES(email_user),
            email_pass=VALUES(email_pass),
            smtp_host=VALUES(smtp_host),
            smtp_port=VALUES(smtp_port),
            smtp_use_tls=VALUES(smtp_use_tls),
            since_date=VALUES(since_date),
            filter_keywords=VALUES(filter_keywords),
            storage_limit_gb=VALUES(storage_limit_gb),
            delete_from_server=0
        """,
        (
            account_id,
            os.environ.get(
                "RB_EMAIL_BOL_ACCOUNT_NAME",
                "BOL Compras Materia Prima",
            ),
            _env_bool("RB_EMAIL_BOL_ENABLED", "1"),
            os.environ.get("RB_EMAIL_BOL_IMAP_HOST", "imap.bol.com.br"),
            int(os.environ.get("RB_EMAIL_BOL_IMAP_PORT", "993")),
            _env_bool("RB_EMAIL_BOL_IMAP_SSL", "1"),
            os.environ.get("RB_EMAIL_BOL_MAILBOX", "INBOX"),
            bol_user,
            bol_pass,
            os.environ.get("RB_EMAIL_BOL_SMTP_HOST", "smtp.bol.com.br"),
            int(os.environ.get("RB_EMAIL_BOL_SMTP_PORT", "587")),
            _env_bool("RB_EMAIL_BOL_SMTP_TLS", "1"),
            os.environ.get("RB_EMAIL_BOL_SINCE_DATE", "2026-01-01"),
            keywords,
            float(os.environ.get("RB_EMAIL_BOL_STORAGE_LIMIT_GB", "5")),
        ),
    )


def ensure_service_schema():
    ddl = [
        """
        CREATE TABLE IF NOT EXISTS service_data_migrations (
            name VARCHAR(120) PRIMARY KEY,
            migrated_at VARCHAR(32) NOT NULL,
            details_json LONGTEXT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS service_scheduler_state (
            name VARCHAR(120) PRIMARY KEY,
            last_run_epoch BIGINT DEFAULT 0,
            updated_at VARCHAR(40)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS importar_xml_configuracao (
            id TINYINT PRIMARY KEY,
            nome_empresa VARCHAR(255),
            raiz_cnpj VARCHAR(20),
            cnpjs_proprios TEXT,
            atualizado_em VARCHAR(32)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS importar_xml_arquivos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nome_arquivo VARCHAR(512),
            caminho_relativo VARCHAR(1024),
            tipo_detectado VARCHAR(40),
            status VARCHAR(40),
            erro TEXT,
            data_upload VARCHAR(40),
            data_importacao VARCHAR(40),
            INDEX idx_importar_xml_arquivos_tipo (tipo_detectado),
            INDEX idx_importar_xml_arquivos_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS importar_xml_estoque_itens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            arquivo_id INT,
            arquivo_origem VARCHAR(512),
            tipo_movimento VARCHAR(60),
            padrao_detectado VARCHAR(80),
            motivo_classificacao TEXT,
            chave_nfe VARCHAR(80),
            numero_nota VARCHAR(80),
            serie VARCHAR(40),
            data_emissao VARCHAR(60),
            natureza_operacao VARCHAR(255),
            cfop VARCHAR(20),
            emitente_cnpj VARCHAR(32),
            emitente_nome VARCHAR(255),
            destinatario_cnpj VARCHAR(32),
            destinatario_nome VARCHAR(255),
            codigo_produto VARCHAR(120),
            descricao_produto VARCHAR(512),
            ncm VARCHAR(30),
            unidade VARCHAR(30),
            quantidade DOUBLE,
            valor_unitario DOUBLE,
            valor_total_item DOUBLE,
            valor_total_nota DOUBLE,
            criado_em VARCHAR(40),
            dados_json LONGTEXT,
            INDEX idx_importar_xml_estoque_arquivo (arquivo_id),
            INDEX idx_importar_xml_estoque_chave (chave_nfe),
            INDEX idx_importar_xml_estoque_nota (numero_nota)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS importar_xml_abastecimentos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            arquivo_id INT,
            arquivo_origem VARCHAR(512),
            posto_cnpj VARCHAR(32),
            posto_nome VARCHAR(255),
            empresa_cnpj VARCHAR(32),
            empresa_nome VARCHAR(255),
            chave_nfe VARCHAR(80),
            numero_nota VARCHAR(80),
            serie VARCHAR(40),
            data_emissao VARCHAR(60),
            placa VARCHAR(20),
            km_final DOUBLE,
            motorista VARCHAR(255),
            combustivel VARCHAR(255),
            litros DOUBLE,
            valor_unitario DOUBLE,
            valor_total DOUBLE,
            valor_produto DOUBLE,
            desconto DOUBLE,
            n_bico VARCHAR(40),
            n_bomba VARCHAR(40),
            n_tanque VARCHAR(40),
            encerrante_inicial DOUBLE,
            encerrante_final DOUBLE,
            texto_complementar LONGTEXT,
            criado_em VARCHAR(40),
            dados_json LONGTEXT,
            INDEX idx_importar_xml_abast_arquivo (arquivo_id),
            INDEX idx_importar_xml_abast_chave (chave_nfe),
            INDEX idx_importar_xml_abast_placa (placa)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS gestor_email_config (
            id TINYINT PRIMARY KEY,
            account_name VARCHAR(120) DEFAULT 'Principal',
            protocol VARCHAR(10) DEFAULT 'pop3',
            enabled TINYINT(1) DEFAULT 1,
            pop_host VARCHAR(255),
            pop_port INT DEFAULT 995,
            use_ssl TINYINT(1) DEFAULT 1,
            mailbox VARCHAR(120) DEFAULT 'INBOX',
            email_user VARCHAR(255),
            email_pass TEXT,
            smtp_host VARCHAR(255) DEFAULT '',
            smtp_port INT DEFAULT 587,
            smtp_use_tls TINYINT(1) DEFAULT 1,
            since_date VARCHAR(10) DEFAULT '',
            filter_keywords TEXT,
            storage_limit_gb DOUBLE DEFAULT 5,
            delete_from_server TINYINT(1) DEFAULT 0
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS gestor_email_mensagens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            account_id INT DEFAULT 1,
            account_label VARCHAR(120) DEFAULT '',
            uid VARCHAR(512) NOT NULL UNIQUE,
            sender_name VARCHAR(255),
            sender_email VARCHAR(255),
            subject TEXT,
            email_date VARCHAR(255),
            imported_at VARCHAR(40),
            filter_matched VARCHAR(255) DEFAULT '',
            body_text LONGTEXT,
            body_html LONGTEXT,
            raw_headers LONGTEXT,
            body_loaded_at VARCHAR(40),
            server_deleted_at VARCHAR(40),
            INDEX idx_gestor_email_conta (account_id),
            INDEX idx_gestor_email_remetente (sender_email)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS gestor_email_anexos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email_id INT NOT NULL,
            filename VARCHAR(512),
            path_relativo VARCHAR(1024),
            legacy_path VARCHAR(2048),
            size_bytes BIGINT,
            created_at VARCHAR(40),
            INDEX idx_gestor_email_anexos_email (email_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS gestor_email_fornecedores (
            id INT AUTO_INCREMENT PRIMARY KEY,
            cnpj VARCHAR(32) NULL,
            nome VARCHAR(255) DEFAULT '',
            categoria VARCHAR(40) DEFAULT 'outros',
            emails TEXT,
            dominios TEXT,
            observacoes TEXT,
            ativo TINYINT(1) DEFAULT 1,
            origem VARCHAR(40) DEFAULT 'manual',
            created_at VARCHAR(40),
            updated_at VARCHAR(40),
            UNIQUE KEY uq_gestor_email_fornecedor_cnpj (cnpj),
            INDEX idx_gestor_email_fornecedor_categoria (categoria),
            INDEX idx_gestor_email_fornecedor_nome (nome)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS manutencao_xml_pre_lancamentos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nota_key VARCHAR(255) NOT NULL,
            importar_xml_abastecimento_id INT NULL,
            chave_nfe VARCHAR(64) DEFAULT '',
            numero_nota VARCHAR(120) DEFAULT '',
            veiculo_id INT NULL,
            placa_xml VARCHAR(20) DEFAULT '',
            sugestao_confianca DECIMAL(6,4) DEFAULT 0,
            origem_veiculo VARCHAR(40) DEFAULT '',
            status VARCHAR(30) DEFAULT 'pendente',
            motivo VARCHAR(500) DEFAULT '',
            emitente_nome VARCHAR(255) DEFAULT '',
            data_documento DATE NULL,
            km INT DEFAULT 0,
            valor DECIMAL(12,2) DEFAULT 0,
            itens_json LONGTEXT NULL,
            manutencao_id INT NULL,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            confirmado_em DATETIME NULL,
            UNIQUE KEY uq_manutencao_xml_nota_key (nota_key),
            INDEX idx_manutencao_xml_status (status),
            INDEX idx_manutencao_xml_veiculo (veiculo_id),
            INDEX idx_manutencao_xml_nota (numero_nota)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS gestor_email_xml_importacoes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            attachment_id INT NOT NULL,
            source_name VARCHAR(512) NOT NULL,
            content_sha256 CHAR(64) NOT NULL,
            fornecedor_id INT NULL,
            destino_importacao VARCHAR(40) DEFAULT '',
            chave_nfe VARCHAR(80) DEFAULT '',
            status VARCHAR(40) NOT NULL,
            tipo_detectado VARCHAR(40) DEFAULT '',
            registros INT DEFAULT 0,
            mensagem TEXT,
            created_at VARCHAR(40),
            updated_at VARCHAR(40),
            UNIQUE KEY uq_gestor_email_xml_origem
                (attachment_id, source_name(220), content_sha256),
            INDEX idx_gestor_email_xml_hash (content_sha256),
            INDEX idx_gestor_email_xml_chave (chave_nfe),
            INDEX idx_gestor_email_xml_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    ]

    conn = _conn()
    try:
        cur = conn.cursor()
        for statement in ddl:
            cur.execute(statement)
        for statement in (
            "ALTER TABLE gestor_email_config ADD COLUMN account_name VARCHAR(120) DEFAULT 'Principal'",
            "ALTER TABLE gestor_email_config ADD COLUMN protocol VARCHAR(10) DEFAULT 'pop3'",
            "ALTER TABLE gestor_email_config ADD COLUMN enabled TINYINT(1) DEFAULT 1",
            "ALTER TABLE gestor_email_config ADD COLUMN mailbox VARCHAR(120) DEFAULT 'INBOX'",
            "ALTER TABLE gestor_email_config ADD COLUMN smtp_host VARCHAR(255) DEFAULT ''",
            "ALTER TABLE gestor_email_config ADD COLUMN smtp_port INT DEFAULT 587",
            "ALTER TABLE gestor_email_config ADD COLUMN smtp_use_tls TINYINT(1) DEFAULT 1",
            "ALTER TABLE gestor_email_config ADD COLUMN since_date VARCHAR(10) DEFAULT ''",
            "ALTER TABLE gestor_email_config ADD COLUMN filter_keywords TEXT",
            "ALTER TABLE gestor_email_mensagens ADD COLUMN account_id INT DEFAULT 1",
            "ALTER TABLE gestor_email_mensagens ADD COLUMN account_label VARCHAR(120) DEFAULT ''",
            "ALTER TABLE gestor_email_mensagens ADD COLUMN filter_matched VARCHAR(255) DEFAULT ''",
            "ALTER TABLE gestor_email_mensagens ADD COLUMN body_text LONGTEXT",
            "ALTER TABLE gestor_email_mensagens ADD COLUMN body_html LONGTEXT",
            "ALTER TABLE gestor_email_mensagens ADD COLUMN raw_headers LONGTEXT",
            "ALTER TABLE gestor_email_mensagens ADD COLUMN body_loaded_at VARCHAR(40)",
            "ALTER TABLE gestor_email_mensagens ADD COLUMN server_deleted_at VARCHAR(40)",
            "ALTER TABLE gestor_email_mensagens ADD INDEX idx_gestor_email_conta (account_id)",
            "ALTER TABLE gestor_email_xml_importacoes ADD COLUMN fornecedor_id INT NULL",
            "ALTER TABLE gestor_email_xml_importacoes ADD COLUMN destino_importacao VARCHAR(40) DEFAULT ''",
            "ALTER TABLE gestor_email_xml_importacoes ADD INDEX idx_gestor_email_xml_fornecedor (fornecedor_id)",
        ):
            try:
                cur.execute(statement)
            except Exception:
                # MariaDB nao oferece ADD COLUMN IF NOT EXISTS em todas as versoes
                # suportadas pelo projeto.
                pass
        cur.execute(
            """
            INSERT IGNORE INTO importar_xml_configuracao
                (id, nome_empresa, raiz_cnpj, cnpjs_proprios, atualizado_em)
            VALUES (1, %s, %s, %s, %s)
            """,
            (
                "BEBIDAS WHITE RIVER LTDA",
                "20984401",
                "20984401000130\n20984401000211",
                _now(),
            ),
        )
        cur.execute(
            """
            INSERT IGNORE INTO gestor_email_config
                (id, account_name, protocol, enabled, pop_host, pop_port,
                 use_ssl, mailbox, email_user, email_pass, smtp_host, smtp_port,
                 smtp_use_tls, since_date, filter_keywords, storage_limit_gb,
                 delete_from_server)
            VALUES (1, 'Principal', 'pop3', 1, '', 995, 1, 'INBOX', '', '',
                    '', 587, 1, '', '', 5, 0)
            """
        )
        _seed_env_email_accounts(cur)
        _backfill_email_suppliers_from_xml(cur)
        _backfill_auto_parts_maintenance(conn)
        conn.commit()
    finally:
        conn.close()


def _copy_tree_missing(source, destination):
    source = Path(source)
    destination = Path(destination)
    if not source.is_dir():
        return {"copied": 0, "existing": 0}
    try:
        if source.resolve() == destination.resolve():
            return {"copied": 0, "existing": sum(1 for p in source.rglob("*") if p.is_file())}
    except FileNotFoundError:
        pass

    copied = 0
    existing = 0
    for src in source.rglob("*"):
        if not src.is_file() or src.is_symlink():
            continue
        rel = src.relative_to(source)
        dst = destination / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            existing += 1
            continue
        shutil.copy2(src, dst)
        copied += 1
    return {"copied": copied, "existing": existing}


def _migration_exists(cur, name):
    cur.execute("SELECT name FROM service_data_migrations WHERE name=%s", (name,))
    return cur.fetchone() is not None


def _mark_migration(cur, name, details):
    cur.execute(
        """
        INSERT INTO service_data_migrations (name, migrated_at, details_json)
        VALUES (%s, %s, %s)
        """,
        (name, _now(), json.dumps(details, ensure_ascii=False)),
    )


def _legacy_attachment_relative(path, email_id, filename):
    normalized = str(path or "").replace("\\", "/")
    if "/anexos/" in normalized:
        rel = normalized.split("/anexos/", 1)[1].strip("/")
        if rel:
            candidate = Path(_legacy_email_root) / "anexos" / rel
            if candidate.is_file():
                return Path(rel)

    root = Path(_legacy_email_root) / "anexos"
    target_names = {str(filename or ""), f"{email_id}_{filename or ''}"}
    for target in target_names:
        if not target:
            continue
        matches = list(root.rglob(target))
        if matches:
            return matches[0].relative_to(root)
    return Path(str(email_id)) / secure_filename(str(filename or "anexo"))


def _migrate_xml_sqlite(cur):
    db_path = Path(_legacy_xml_root) / "homologacao_xml.sqlite3"
    if not db_path.is_file():
        return {"skipped": "SQLite do ImportarXml nao encontrado."}

    legacy = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    legacy.row_factory = sqlite3.Row
    counts = {}
    try:
        config = legacy.execute("SELECT * FROM configuracao_empresa WHERE id=1").fetchone()
        if config:
            cur.execute(
                """
                INSERT INTO importar_xml_configuracao
                    (id, nome_empresa, raiz_cnpj, cnpjs_proprios, atualizado_em)
                VALUES (1, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    nome_empresa=VALUES(nome_empresa),
                    raiz_cnpj=VALUES(raiz_cnpj),
                    cnpjs_proprios=VALUES(cnpjs_proprios),
                    atualizado_em=VALUES(atualizado_em)
                """,
                (
                    config["nome_empresa"],
                    config["raiz_cnpj"],
                    config["cnpjs_proprios"],
                    config["atualizado_em"],
                ),
            )

        files = legacy.execute("SELECT * FROM arquivos_importados ORDER BY id").fetchall()
        for row in files:
            cur.execute(
                """
                INSERT IGNORE INTO importar_xml_arquivos
                    (id, nome_arquivo, caminho_relativo, tipo_detectado, status,
                     erro, data_upload, data_importacao)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row["id"],
                    row["nome_arquivo"],
                    Path(row["caminho"] or row["nome_arquivo"] or "").name,
                    row["tipo_detectado"],
                    row["status"],
                    row["erro"],
                    row["data_upload"],
                    row["data_importacao"],
                ),
            )
        counts["arquivos"] = len(files)

        columns = [
            "id", "arquivo_id", "arquivo_origem", "tipo_movimento",
            "padrao_detectado", "motivo_classificacao", "chave_nfe",
            "numero_nota", "serie", "data_emissao", "natureza_operacao",
            "cfop", "emitente_cnpj", "emitente_nome", "destinatario_cnpj",
            "destinatario_nome", "codigo_produto", "descricao_produto", "ncm",
            "unidade", "quantidade", "valor_unitario", "valor_total_item",
            "valor_total_nota", "criado_em", "dados_json",
        ]
        items = legacy.execute("SELECT * FROM estoque_itens ORDER BY id").fetchall()
        placeholders = ", ".join(["%s"] * len(columns))
        cur.executemany(
            f"""
            INSERT IGNORE INTO importar_xml_estoque_itens
                ({", ".join(columns)})
            VALUES ({placeholders})
            """,
            [tuple(row[col] for col in columns) for row in items],
        )
        counts["estoque_itens"] = len(items)

        columns = [
            "id", "arquivo_id", "arquivo_origem", "posto_cnpj", "posto_nome",
            "empresa_cnpj", "empresa_nome", "chave_nfe", "numero_nota", "serie",
            "data_emissao", "placa", "km_final", "motorista", "combustivel",
            "litros", "valor_unitario", "valor_total", "valor_produto",
            "desconto", "n_bico", "n_bomba", "n_tanque", "encerrante_inicial",
            "encerrante_final", "texto_complementar", "criado_em", "dados_json",
        ]
        abastecimentos = legacy.execute("SELECT * FROM abastecimentos ORDER BY id").fetchall()
        placeholders = ", ".join(["%s"] * len(columns))
        cur.executemany(
            f"""
            INSERT IGNORE INTO importar_xml_abastecimentos
                ({", ".join(columns)})
            VALUES ({placeholders})
            """,
            [tuple(row[col] for col in columns) for row in abastecimentos],
        )
        counts["abastecimentos"] = len(abastecimentos)
    finally:
        legacy.close()
    return counts


def _migrate_email_sqlite(cur):
    db_path = Path(_legacy_email_root) / "emails.db"
    if not db_path.is_file():
        return {"skipped": "SQLite do GestorEmails nao encontrado."}

    legacy = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    legacy.row_factory = sqlite3.Row
    counts = {}
    try:
        config = legacy.execute("SELECT * FROM config WHERE id=1").fetchone()
        if config:
            cur.execute(
                """
                INSERT INTO gestor_email_config
                    (id, pop_host, pop_port, use_ssl, email_user, email_pass,
                     storage_limit_gb, delete_from_server)
                VALUES (1, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    pop_host=VALUES(pop_host),
                    pop_port=VALUES(pop_port),
                    use_ssl=VALUES(use_ssl),
                    email_user=VALUES(email_user),
                    email_pass=VALUES(email_pass),
                    storage_limit_gb=VALUES(storage_limit_gb),
                    delete_from_server=VALUES(delete_from_server)
                """,
                (
                    config["pop_host"],
                    config["pop_port"],
                    config["use_ssl"],
                    config["email_user"],
                    config["email_pass"],
                    config["storage_limit_gb"],
                    config["delete_from_server"],
                ),
            )

        messages = legacy.execute("SELECT * FROM emails ORDER BY id").fetchall()
        cur.executemany(
            """
            INSERT IGNORE INTO gestor_email_mensagens
                (id, uid, sender_name, sender_email, subject, email_date, imported_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    row["id"], row["uid"], row["sender_name"], row["sender_email"],
                    row["subject"], row["email_date"], row["imported_at"],
                )
                for row in messages
            ],
        )
        counts["emails"] = len(messages)

        attachments = legacy.execute("SELECT * FROM attachments ORDER BY id").fetchall()
        values = []
        for row in attachments:
            rel = _legacy_attachment_relative(
                row["path"], row["email_id"], row["filename"]
            )
            values.append(
                (
                    row["id"],
                    row["email_id"],
                    row["filename"],
                    rel.as_posix(),
                    row["path"],
                    row["size_bytes"],
                    row["created_at"],
                )
            )
        cur.executemany(
            """
            INSERT IGNORE INTO gestor_email_anexos
                (id, email_id, filename, path_relativo, legacy_path,
                 size_bytes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            values,
        )
        counts["anexos"] = len(attachments)
    finally:
        legacy.close()
    return counts


def migrate_legacy_service_data():
    details = {
        "xml_files": _copy_tree_missing(
            Path(_legacy_xml_root) / "uploads_xml_homologacao",
            _xml_upload_dir,
        ),
        "email_files": _copy_tree_missing(
            Path(_legacy_email_root) / "anexos",
            _email_attachment_dir,
        ),
    }

    conn = _conn()
    try:
        cur = conn.cursor()
        if not _migration_exists(cur, "importar_xml_sqlite_v1"):
            result = _migrate_xml_sqlite(cur)
            if "skipped" not in result:
                _mark_migration(cur, "importar_xml_sqlite_v1", result)
            details["importar_xml"] = result
        if not _migration_exists(cur, "gestor_email_sqlite_v1"):
            result = _migrate_email_sqlite(cur)
            if "skipped" not in result:
                _mark_migration(cur, "gestor_email_sqlite_v1", result)
            details["gestor_email"] = result
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return details


XML_BASE = """
<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Importar XML</title>
<style>
body{font-family:Arial,sans-serif;background:#f3f3f3;margin:0;padding:22px}
.box{background:#fff;padding:20px;border-radius:10px;max-width:1400px;margin:auto}
nav a{color:#0b63ce;text-decoration:none;margin-right:14px;line-height:2}
input,textarea,button{padding:8px;margin:5px 0;max-width:800px;width:100%;box-sizing:border-box}
button{background:#0b63ce;color:#fff;border:0;border-radius:6px;cursor:pointer}
button.secondary{background:#546e7a}
button.danger{background:#b71c1c}
table{border-collapse:collapse;width:100%;margin-top:15px}
th,td{border:1px solid #ddd;padding:8px;font-size:14px;vertical-align:top}
th{background:#eee}.msg{background:#e8f5e9;padding:10px;border-radius:6px;margin:10px 0}
.erro{background:#ffebee}.badge{display:inline-block;padding:4px 7px;border-radius:5px;background:#eee}
.abast{background:#bbdefb}.entrada{background:#c8e6c9}.saida{background:#ffe0b2}
.small{color:#555;font-size:13px}.scroll{overflow:auto}
.pending-box{border:2px solid #ef6c00;background:#fff8e1;padding:14px;border-radius:8px;margin:15px 0}
.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.form-grid label{font-weight:bold}.form-grid input,.form-grid select{margin-top:4px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.actions button{width:auto;min-width:160px}
.progress{height:28px;background:#ddd;border-radius:10px;overflow:hidden;margin:12px 0;max-width:800px}
.progress>div{height:28px;line-height:28px;text-align:center;color:#fff;background:#0b63ce;width:0}
</style>
</head>
<body><div class="box">
<nav>
<a href="{{ url_for('importar_xml.index') }}">Importar XML</a>
<a href="{{ url_for('importar_xml.estoque') }}">Estoque</a>
<a href="{{ url_for('importar_xml.abastecimentos') }}">Abastecimentos</a>
<a href="{{ url_for('importar_xml.arquivos') }}">Arquivos</a>
<a href="{{ url_for('importar_xml.config') }}">Configuracao</a>
<a href="{{ url_for('gestor_emails.index') }}">Gestor de e-mails</a>
<a href="/">Sistema principal</a>
</nav><hr>
{% with messages = get_flashed_messages(with_categories=true) %}
{% for category, message in messages %}
<div class="msg {{ 'erro' if category == 'erro' else '' }}">{{ message }}</div>
{% endfor %}
{% endwith %}
{{ body|safe }}
</div></body></html>
"""


def _xml_page(body):
    return render_template_string(XML_BASE, body=body)


def _xml_config():
    row = _row("SELECT * FROM importar_xml_configuracao WHERE id=1") or {}
    own = set()
    for value in str(row.get("cnpjs_proprios") or "").splitlines():
        value = so_num(value)
        if value:
            own.add(value)
    name = row.get("nome_empresa") or "BEBIDAS WHITE RIVER LTDA"
    from ImportarXml.importador_xml_homologacao import normalizar_nome
    return {
        "nome_empresa": name,
        "nome_norm": normalizar_nome(name),
        "raiz_cnpj": so_num(row.get("raiz_cnpj") or "20984401"),
        "cnpjs_proprios": own,
    }


def _import_xml_file(path, original_name):
    conn = _conn()
    source_abastecimento_id = 0
    try:
        cab, items = parse_nfe(path)
        kind = "ABASTECIMENTO" if eh_combustivel(cab, items) else "ESTOQUE"
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO importar_xml_arquivos
                (nome_arquivo, caminho_relativo, tipo_detectado, status, erro,
                 data_upload, data_importacao)
            VALUES (%s, %s, %s, 'PROCESSANDO', NULL, %s, %s)
            """,
            (original_name, Path(path).name, kind, _now(), _now()),
        )
        file_id = cur.lastrowid

        if kind == "ABASTECIMENTO":
            data = extrair_abastecimento(cab, items)
            cur.execute(
                """
                INSERT INTO importar_xml_abastecimentos (
                    arquivo_id, arquivo_origem, posto_cnpj, posto_nome,
                    empresa_cnpj, empresa_nome, chave_nfe, numero_nota, serie,
                    data_emissao, placa, km_final, motorista, combustivel,
                    litros, valor_unitario, valor_total, valor_produto,
                    desconto, n_bico, n_bomba, n_tanque, encerrante_inicial,
                    encerrante_final, texto_complementar, criado_em, dados_json
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                """,
                (
                    file_id, original_name, data["posto_cnpj"], data["posto_nome"],
                    data["empresa_cnpj"], data["empresa_nome"], data["chave_nfe"],
                    data["numero_nota"], data["serie"], data["data_emissao"],
                    data["placa"], data["km_final"], data["motorista"],
                    data["combustivel"], data["litros"], data["valor_unitario"],
                    data["valor_total"], data["valor_produto"], data["desconto"],
                    data["n_bico"], data["n_bomba"], data["n_tanque"],
                    data["encerrante_inicial"], data["encerrante_final"],
                    data["texto_complementar"], _now(),
                    json.dumps({"cab": cab, "itens": items}, ensure_ascii=False),
                ),
            )
            source_abastecimento_id = cur.lastrowid
            total = 1
        else:
            movement, pattern, reason = classificar_estoque(cab, _xml_config())
            total = 0
            for item in items:
                cur.execute(
                    """
                    INSERT INTO importar_xml_estoque_itens (
                        arquivo_id, arquivo_origem, tipo_movimento,
                        padrao_detectado, motivo_classificacao, chave_nfe,
                        numero_nota, serie, data_emissao, natureza_operacao,
                        cfop, emitente_cnpj, emitente_nome, destinatario_cnpj,
                        destinatario_nome, codigo_produto, descricao_produto,
                        ncm, unidade, quantidade, valor_unitario,
                        valor_total_item, valor_total_nota, criado_em, dados_json
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s
                    )
                    """,
                    (
                        file_id, original_name, movement, pattern, reason,
                        cab["chave_nfe"], cab["numero_nota"], cab["serie"],
                        cab["data_emissao"], cab["natureza_operacao"], item["cfop"],
                        cab["emitente_cnpj"], cab["emitente_nome"],
                        cab["destinatario_cnpj"], cab["destinatario_nome"],
                        item["codigo_produto"], item["descricao_produto"],
                        item["ncm"], item["unidade"], item["quantidade"],
                        item["valor_unitario"], item["valor_total_item"],
                        cab["valor_total_nota"], _now(),
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
                total += 1

        cur.execute(
            "UPDATE importar_xml_arquivos SET status='IMPORTADO', erro=NULL WHERE id=%s",
            (file_id,),
        )
        conn.commit()
        callback_message = ""
        if (
            kind == "ABASTECIMENTO"
            and source_abastecimento_id > 0
            and callable(_abastecimento_import_callback)
        ):
            try:
                _abastecimento_import_callback(source_abastecimento_id)
            except Exception as exc:
                callback_message = (
                    "XML salvo, mas o vinculo automatico com o abastecimento "
                    f"ficou pendente: {exc}"
                )
        return True, kind, total, callback_message
    except Exception as exc:
        conn.rollback()
        return False, "ERRO", 0, str(exc)
    finally:
        conn.close()


def _set_xml_progress(job_id, **values):
    with XML_PROGRESS_LOCK:
        XML_PROGRESS.setdefault(job_id, {}).update(values)


def _process_xml_job(job_id, files):
    stock = fuel = records = errors = 0
    total = len(files)
    for index, (name, path) in enumerate(files, start=1):
        _set_xml_progress(
            job_id,
            arquivo_atual=name,
            mensagem=f"Importando {index} de {total}: {name}",
            processados=index - 1,
            percentual=int(((index - 1) / total) * 100) if total else 0,
        )
        success, kind, count, message = _import_xml_file(path, name)
        if success:
            records += count
            if kind == "ABASTECIMENTO":
                fuel += 1
            else:
                stock += 1
        else:
            errors += 1
        _set_xml_progress(
            job_id,
            processados=index,
            percentual=int((index / total) * 100) if total else 100,
            estoque=stock,
            abastecimentos=fuel,
            registros=records,
            erros=errors,
            ultimo_erro=message if not success else "",
        )
    _set_xml_progress(
        job_id,
        processados=total,
        percentual=100,
        arquivo_atual="-",
        mensagem=f"Importacao concluida: {total - errors} XML(s), {records} registro(s), {errors} erro(s).",
        finalizado=True,
    )


@XML_BP.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        uploads = [
            item for item in request.files.getlist("xmls")
            if item and item.filename and item.filename.lower().endswith(".xml")
        ]
        if not uploads:
            flash("Selecione um ou mais XMLs.", "erro")
            return redirect(url_for("importar_xml.index"))
        Path(_xml_upload_dir).mkdir(parents=True, exist_ok=True)
        for upload in uploads:
            name = secure_filename(upload.filename)
            path = Path(_xml_upload_dir) / f"{uuid.uuid4().hex}_{name}"
            upload.save(path)
            success, _, _, message = _import_xml_file(path, name)
            if not success:
                flash(f"{name}: {message}", "erro")
        return redirect(url_for("importar_xml.arquivos"))

    start_url = url_for("importar_xml.importar_com_progresso")
    status_base = url_for("importar_xml.status_importacao", job_id="JOB_ID").replace("JOB_ID", "")
    return _xml_page(f"""
    <h2>Importador XML</h2>
    <p>Os registros sao gravados no banco principal. Os XML permanecem no armazenamento persistente.</p>
    <form id="xml-form" method="post" enctype="multipart/form-data">
      <input id="xmls" type="file" name="xmls" accept=".xml" multiple required>
      <button id="xml-submit" type="submit">Importar XMLs</button>
    </form>
    <div id="xml-status" style="display:none">
      <p id="xml-message">Enviando...</p>
      <div class="progress"><div id="xml-progress">0%</div></div>
      <p>Processados: <span id="xml-processed">0</span>/<span id="xml-total">0</span></p>
    </div>
    <script>
    const form=document.getElementById("xml-form");
    form.addEventListener("submit", async (event)=>{{
      event.preventDefault();
      const status=document.getElementById("xml-status");
      status.style.display="block";
      const response=await fetch({json.dumps(start_url)},{{method:"POST",body:new FormData(form)}});
      const data=await response.json();
      if(!data.ok){{document.getElementById("xml-message").textContent=data.erro;return;}}
      const timer=setInterval(async()=>{{
        const current=await fetch({json.dumps(status_base)}+data.job_id).then(r=>r.json());
        document.getElementById("xml-message").textContent=current.mensagem||"Processando...";
        document.getElementById("xml-processed").textContent=current.processados||0;
        document.getElementById("xml-total").textContent=current.total||0;
        const bar=document.getElementById("xml-progress");
        bar.style.width=(current.percentual||0)+"%";
        bar.textContent=(current.percentual||0)+"%";
        if(current.finalizado){{clearInterval(timer);}}
      }},700);
    }});
    </script>
    """)


@XML_BP.route("/importar-com-progresso", methods=["POST"])
def importar_com_progresso():
    uploads = [
        item for item in request.files.getlist("xmls")
        if item and item.filename and item.filename.lower().endswith(".xml")
    ]
    if not uploads:
        return jsonify({"ok": False, "erro": "Selecione um ou mais XMLs."}), 400
    Path(_xml_upload_dir).mkdir(parents=True, exist_ok=True)
    files = []
    for upload in uploads:
        name = secure_filename(upload.filename)
        path = Path(_xml_upload_dir) / f"{uuid.uuid4().hex}_{name}"
        upload.save(path)
        files.append((name, str(path)))
    job_id = uuid.uuid4().hex
    _set_xml_progress(
        job_id,
        total=len(files),
        processados=0,
        percentual=0,
        arquivo_atual="-",
        estoque=0,
        abastecimentos=0,
        registros=0,
        erros=0,
        mensagem="Iniciando importacao...",
        finalizado=False,
    )
    threading.Thread(target=_process_xml_job, args=(job_id, files), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@XML_BP.route("/status-importacao/<job_id>")
def status_importacao(job_id):
    with XML_PROGRESS_LOCK:
        data = dict(XML_PROGRESS.get(job_id) or {})
    if not data:
        return jsonify({"ok": False, "erro": "Importacao nao encontrada."}), 404
    return jsonify({"ok": True, **data})


@XML_BP.route("/config", methods=["GET", "POST"])
def config():
    if request.method == "POST":
        _execute(
            """
            UPDATE importar_xml_configuracao
            SET nome_empresa=%s, raiz_cnpj=%s, cnpjs_proprios=%s, atualizado_em=%s
            WHERE id=1
            """,
            (
                request.form.get("nome_empresa", ""),
                so_num(request.form.get("raiz_cnpj", ""))[:8],
                request.form.get("cnpjs_proprios", ""),
                _now(),
            ),
        )
        flash("Configuracao salva.")
        return redirect(url_for("importar_xml.config"))
    data = _row("SELECT * FROM importar_xml_configuracao WHERE id=1") or {}
    return _xml_page(f"""
    <h2>Configuracao da empresa</h2>
    <form method="post">
      <label>Nome principal</label>
      <input name="nome_empresa" value="{html.escape(str(data.get('nome_empresa') or ''))}">
      <label>Raiz do CNPJ</label>
      <input name="raiz_cnpj" value="{html.escape(str(data.get('raiz_cnpj') or ''))}">
      <label>CNPJs proprios, um por linha</label>
      <textarea name="cnpjs_proprios" rows="6">{html.escape(str(data.get('cnpjs_proprios') or ''))}</textarea>
      <button>Salvar</button>
    </form>
    """)


@XML_BP.route("/arquivos")
def arquivos():
    rows = _rows("SELECT * FROM importar_xml_arquivos ORDER BY id DESC LIMIT 500")
    table = "".join(
        f"<tr><td>{row['id']}</td><td>{html.escape(str(row.get('nome_arquivo') or ''))}</td>"
        f"<td>{html.escape(str(row.get('tipo_detectado') or ''))}</td>"
        f"<td>{html.escape(str(row.get('status') or ''))}</td>"
        f"<td>{html.escape(str(row.get('erro') or ''))}</td>"
        f"<td>{html.escape(str(row.get('data_importacao') or ''))}</td></tr>"
        for row in rows
    )
    return _xml_page(
        "<h2>Arquivos importados</h2><div class='scroll'><table>"
        "<tr><th>ID</th><th>Arquivo</th><th>Tipo</th><th>Status</th><th>Erro</th><th>Data</th></tr>"
        f"{table}</table></div>"
    )


@XML_BP.route("/estoque")
def estoque():
    query = request.args.get("q", "").strip()
    params = ()
    where = ""
    if query:
        term = f"%{query}%"
        where = """
        WHERE descricao_produto LIKE %s OR codigo_produto LIKE %s
           OR numero_nota LIKE %s OR emitente_nome LIKE %s
           OR destinatario_nome LIKE %s
        """
        params = (term, term, term, term, term)
    rows = _rows(
        f"SELECT * FROM importar_xml_estoque_itens {where} ORDER BY id DESC LIMIT 1000",
        params,
    )
    table = "".join(
        f"<tr><td>{row['id']}</td><td>{html.escape(str(row.get('tipo_movimento') or ''))}</td>"
        f"<td>{html.escape(str(row.get('numero_nota') or ''))}</td>"
        f"<td>{html.escape(str(row.get('data_emissao') or ''))}</td>"
        f"<td>{html.escape(fmt_cnpj(row.get('emitente_cnpj')))}<br>{html.escape(str(row.get('emitente_nome') or ''))}</td>"
        f"<td>{html.escape(str(row.get('codigo_produto') or ''))}</td>"
        f"<td>{html.escape(str(row.get('descricao_produto') or ''))}</td>"
        f"<td>{html.escape(str(row.get('cfop') or ''))}</td>"
        f"<td>{row.get('quantidade') or ''}</td><td>{row.get('valor_total_item') or ''}</td></tr>"
        for row in rows
    )
    return _xml_page(f"""
    <h2>Itens de estoque</h2>
    <form method="get"><input name="q" value="{html.escape(query)}" placeholder="Buscar produto, nota ou empresa"><button>Buscar</button></form>
    <p><a href="{url_for('importar_xml.exportar_estoque')}">Exportar CSV</a></p>
    <div class="scroll"><table><tr><th>ID</th><th>Movimento</th><th>Nota</th><th>Emissao</th><th>Emitente</th><th>Codigo</th><th>Produto</th><th>CFOP</th><th>Qtd</th><th>Valor</th></tr>{table}</table></div>
    """)


@XML_BP.route("/abastecimentos")
def abastecimentos():
    query = request.args.get("q", "").strip()
    params = []
    conditions = []
    search_condition = ""
    if query:
        term = f"%{query}%"
        search_condition = """
            (
                x.placa LIKE %s OR x.posto_nome LIKE %s
                OR x.combustivel LIKE %s OR x.numero_nota LIKE %s
                OR x.motorista LIKE %s
            )
            """
        conditions.append(search_condition)
        params.extend((term, term, term, term, term))
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    pending_conditions = ["v.status='pendente'"]
    pending_params = []
    if search_condition:
        pending_conditions.append(search_condition)
        pending_params.extend(params)
    pending_rows = _rows(
        f"""
        SELECT
            x.*,
            v.status AS vinculo_status,
            v.motivo AS vinculo_motivo,
            v.abastecimento_id,
            v.veiculo_id AS vinculo_veiculo_id
        FROM importar_xml_abastecimentos x
        INNER JOIN abastecimento_xml_vinculos v
            ON v.importar_xml_abastecimento_id=x.id
        WHERE {' AND '.join(pending_conditions)}
        ORDER BY x.id DESC
        """,
        tuple(pending_params),
    )
    rows = _rows(
        f"""
        SELECT
            x.*,
            v.status AS vinculo_status,
            v.motivo AS vinculo_motivo,
            v.abastecimento_id,
            v.veiculo_id AS vinculo_veiculo_id
        FROM importar_xml_abastecimentos x
        LEFT JOIN abastecimento_xml_vinculos v
            ON v.importar_xml_abastecimento_id=x.id
        {where}
        ORDER BY x.id DESC
        LIMIT 1000
        """,
        tuple(params),
    )
    pending_table = "".join(
        f"<tr><td>{row['id']}</td>"
        f"<td>{html.escape(str(row.get('numero_nota') or ''))}</td>"
        f"<td>{html.escape(str(row.get('data_emissao') or ''))}</td>"
        f"<td>{html.escape(str(row.get('placa') or '-'))}</td>"
        f"<td>{html.escape(str(row.get('combustivel') or ''))}</td>"
        f"<td>{row.get('litros') or ''}</td>"
        f"<td>{html.escape(str(row.get('vinculo_motivo') or 'Revisao necessaria'))}</td>"
        f"<td><a href='{url_for('importar_xml.revisar_abastecimento', xml_id=row['id'])}'>Revisar</a></td></tr>"
        for row in pending_rows
    )

    def action_link(row):
        if str(row.get("vinculo_status") or "").lower() != "pendente":
            return ""
        href = url_for(
            "importar_xml.revisar_abastecimento",
            xml_id=row["id"],
        )
        return f"<a href='{href}'>Revisar</a>"

    table = "".join(
        f"<tr><td>{row['id']}</td><td>{html.escape(str(row.get('numero_nota') or ''))}</td>"
        f"<td>{html.escape(str(row.get('data_emissao') or ''))}</td>"
        f"<td>{html.escape(str(row.get('posto_nome') or ''))}</td>"
        f"<td>{html.escape(str(row.get('placa') or ''))}</td>"
        f"<td>{row.get('km_final') or ''}</td>"
        f"<td>{html.escape(str(row.get('motorista') or ''))}</td>"
        f"<td>{html.escape(str(row.get('combustivel') or ''))}</td>"
        f"<td>{row.get('litros') or ''}</td><td>{row.get('valor_total') or ''}</td>"
        f"<td>{html.escape(str(row.get('vinculo_status') or 'sem vinculo'))}</td>"
        f"<td>{action_link(row)}</td></tr>"
        for row in rows
    )
    return _xml_page(f"""
    <h2>Abastecimentos importados</h2>
    <form method="get"><input name="q" value="{html.escape(query)}" placeholder="Buscar placa, posto, combustivel ou nota"><button>Buscar</button></form>
    <div class="pending-box">
      <h3>Pendencias de abastecimento: {len(pending_rows)}</h3>
      <p>Revise o veiculo, KM, combustivel, quantidade e valor para concluir o lancamento no modulo de frota.</p>
      <div class="scroll"><table>
        <tr><th>ID</th><th>Nota</th><th>Emissao</th><th>Placa XML</th><th>Produto</th><th>Qtd</th><th>Motivo</th><th>Acao</th></tr>
        {pending_table or '<tr><td colspan="8">Nenhuma pendencia neste filtro.</td></tr>'}
      </table></div>
    </div>
    <p><a href="{url_for('importar_xml.exportar_abastecimentos')}">Exportar CSV</a></p>
    <div class="scroll"><table><tr><th>ID</th><th>Nota</th><th>Emissao</th><th>Posto</th><th>Placa</th><th>KM</th><th>Motorista</th><th>Combustivel</th><th>Litros</th><th>Valor</th><th>Status</th><th>Acao</th></tr>{table}</table></div>
    """)


def _abastecimento_form_float(value, field):
    text = str(value or "").strip().replace(",", ".")
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} invalido") from exc
    if number <= 0:
        raise ValueError(f"{field} deve ser maior que zero")
    return number


def _abastecimento_pending_form(form, vehicle):
    if not vehicle:
        raise ValueError("selecione um veiculo cadastrado")
    plate = str(vehicle.get("placa") or "").strip()
    if not plate:
        raise ValueError("o veiculo selecionado nao possui placa cadastrada")
    fuel = str(form.get("combustivel") or "").strip().lower()
    fuel_labels = {
        "diesel_s10": "OLEO DIESEL B S10",
        "diesel_500": "OLEO DIESEL B S500",
        "gasolina": "GASOLINA COMUM",
        "etanol": "ETANOL HIDRATADO COMUM",
        "arla": "ARLA 32",
    }
    if fuel not in fuel_labels:
        raise ValueError(
            "selecione Diesel S10, Diesel 500, Gasolina, Etanol ou Arla"
        )
    date_text = str(form.get("data_emissao") or "").strip()
    if not date_text:
        raise ValueError("informe a data do abastecimento")
    post = str(form.get("posto_nome") or "").strip()
    if not post:
        raise ValueError("informe o posto")
    liters = _abastecimento_form_float(form.get("litros"), "quantidade")
    total = _abastecimento_form_float(form.get("valor_total"), "valor")
    return {
        "veiculo_id": int(vehicle["id"]),
        "placa": plate,
        "km_final": _abastecimento_form_float(form.get("km_final"), "KM"),
        "posto_nome": post,
        "data_emissao": date_text,
        "motorista": str(form.get("motorista") or "").strip(),
        "combustivel": fuel_labels[fuel],
        "litros": liters,
        "valor_total": total,
        "valor_produto": total,
        "valor_unitario": total / liters,
    }


@XML_BP.route("/abastecimentos/<int:xml_id>", methods=["GET", "POST"])
def revisar_abastecimento(xml_id):
    row = _row(
        """
        SELECT
            x.*,
            v.status AS vinculo_status,
            v.motivo AS vinculo_motivo,
            v.abastecimento_id,
            v.veiculo_id AS vinculo_veiculo_id
        FROM importar_xml_abastecimentos x
        LEFT JOIN abastecimento_xml_vinculos v
            ON v.importar_xml_abastecimento_id=x.id
        WHERE x.id=%s
        """,
        (xml_id,),
    )
    if not row:
        return _xml_page("<h2>Abastecimento nao encontrado.</h2>"), 404

    if request.method == "POST":
        action = str(request.form.get("acao") or "finalizar").strip().lower()
        if action == "ignorar":
            reason = str(
                request.form.get("motivo_ignorar")
                or "Ignorado manualmente na revisao do Importar XML."
            ).strip()
            _execute(
                """
                UPDATE abastecimento_xml_vinculos
                SET status='ignorado', vinculacao_origem='revisao_manual',
                    motivo=%s, atualizado_em=NOW()
                WHERE importar_xml_abastecimento_id=%s
                  AND status='pendente'
                """,
                (reason[:500], xml_id),
            )
            flash("Pendencia marcada como ignorada.")
            return redirect(url_for("importar_xml.abastecimentos"))

        try:
            vehicle_id = int(request.form.get("veiculo_id") or 0)
        except (TypeError, ValueError):
            vehicle_id = 0
        vehicle = _row(
            """
            SELECT id, nome, placa, modelo, combustivel_padrao, km_atual
            FROM veiculos
            WHERE id=%s
            """,
            (vehicle_id,),
        )
        try:
            values = _abastecimento_pending_form(request.form, vehicle)
        except (TypeError, ValueError) as exc:
            flash(str(exc), "erro")
            return redirect(
                url_for("importar_xml.revisar_abastecimento", xml_id=xml_id)
            )

        _execute(
            """
            UPDATE importar_xml_abastecimentos
            SET placa=%s, km_final=%s, posto_nome=%s, data_emissao=%s,
                motorista=%s, combustivel=%s, litros=%s, valor_unitario=%s,
                valor_total=%s, valor_produto=%s
            WHERE id=%s
            """,
            (
                values["placa"],
                values["km_final"],
                values["posto_nome"],
                values["data_emissao"],
                values["motorista"],
                values["combustivel"],
                values["litros"],
                values["valor_unitario"],
                values["valor_total"],
                values["valor_produto"],
                xml_id,
            ),
        )
        if callable(_abastecimento_import_callback):
            try:
                _abastecimento_import_callback(xml_id)
            except Exception as exc:
                flash(f"Dados salvos, mas a finalizacao falhou: {exc}", "erro")
                return redirect(
                    url_for("importar_xml.revisar_abastecimento", xml_id=xml_id)
                )
        result = _row(
            """
            SELECT status, motivo, abastecimento_id
            FROM abastecimento_xml_vinculos
            WHERE importar_xml_abastecimento_id=%s
            ORDER BY id DESC
            LIMIT 1
            """,
            (xml_id,),
        ) or {}
        if str(result.get("status") or "").lower() in {"criado", "vinculado"}:
            flash(
                "Abastecimento finalizado e vinculado ao modulo de frota."
            )
            return redirect(url_for("importar_xml.abastecimentos"))
        flash(
            str(result.get("motivo") or "A pendencia ainda precisa de revisao."),
            "erro",
        )
        return redirect(
            url_for("importar_xml.revisar_abastecimento", xml_id=xml_id)
        )

    vehicles = _rows(
        """
        SELECT id, nome, placa, modelo, combustivel_padrao, km_atual
        FROM veiculos
        ORDER BY CAST(nome AS UNSIGNED), nome, placa
        """
    )
    selected_vehicle = int(row.get("vinculo_veiculo_id") or 0)
    options = ["<option value=''>Selecione o veiculo</option>"]
    for vehicle in vehicles:
        selected = " selected" if int(vehicle["id"]) == selected_vehicle else ""
        label = " / ".join(
            value for value in (
                str(vehicle.get("nome") or "").strip(),
                str(vehicle.get("placa") or "").strip(),
                str(vehicle.get("modelo") or "").strip(),
            ) if value
        )
        options.append(
            f"<option value='{vehicle['id']}' data-fuel='{html.escape(str(vehicle.get('combustivel_padrao') or ''))}'{selected}>"
            f"{html.escape(label)}</option>"
        )
    fuel_value = "diesel_s10"
    fuel_text = str(row.get("combustivel") or "").upper()
    if "ARLA" in fuel_text:
        fuel_value = "arla"
    elif "ETANOL" in fuel_text or "ALCOOL" in fuel_text or "ÁLCOOL" in fuel_text:
        fuel_value = "etanol"
    elif "GASOLINA" in fuel_text:
        fuel_value = "gasolina"
    elif any(token in fuel_text for token in ("S500", "S-500", "DIESEL 500")):
        fuel_value = "diesel_500"
    date_value = str(row.get("data_emissao") or "")[:16]
    return _xml_page(f"""
    <h2>Revisar abastecimento XML #{xml_id}</h2>
    <div class="pending-box">
      <b>Motivo atual:</b> {html.escape(str(row.get('vinculo_motivo') or 'Revisao necessaria'))}<br>
      <span class="small">NF-e {html.escape(str(row.get('numero_nota') or '-'))} | Chave {html.escape(str(row.get('chave_nfe') or '-'))}</span>
    </div>
    <form method="post">
      <div class="form-grid">
        <label>Veiculo
          <select name="veiculo_id" id="pendingVehicle" required>{''.join(options)}</select>
        </label>
        <label>KM
          <input name="km_final" type="number" min="1" step="1" value="{html.escape(str(row.get('km_final') or ''))}" required>
        </label>
        <label>Combustivel
          <select name="combustivel" id="pendingFuel" required>
            <option value="diesel_s10" {'selected' if fuel_value == 'diesel_s10' else ''}>Diesel S10</option>
            <option value="diesel_500" {'selected' if fuel_value == 'diesel_500' else ''}>Diesel 500</option>
            <option value="gasolina" {'selected' if fuel_value == 'gasolina' else ''}>Gasolina</option>
            <option value="etanol" {'selected' if fuel_value == 'etanol' else ''}>Etanol</option>
            <option value="arla" {'selected' if fuel_value == 'arla' else ''}>Arla</option>
          </select>
        </label>
        <label>Quantidade
          <input name="litros" type="number" min="0.001" step="0.001" value="{html.escape(str(row.get('litros') or ''))}" required>
        </label>
        <label>Valor do produto
          <input name="valor_total" type="number" min="0.01" step="0.01" value="{html.escape(str(row.get('valor_produto') or row.get('valor_total') or ''))}" required>
        </label>
        <label>Data
          <input name="data_emissao" type="datetime-local" value="{html.escape(date_value)}" required>
        </label>
        <label>Posto
          <input name="posto_nome" value="{html.escape(str(row.get('posto_nome') or ''))}" required>
        </label>
        <label>Motorista
          <input name="motorista" value="{html.escape(str(row.get('motorista') or ''))}">
        </label>
      </div>
      <div class="actions">
        <button name="acao" value="finalizar">Salvar e finalizar</button>
        <button type="button" class="secondary" onclick='location.href={json.dumps(url_for('importar_xml.abastecimentos'))}'>Cancelar</button>
      </div>
    </form>
    <hr>
    <form method="post" onsubmit="return confirm('Ignorar esta pendencia sem criar abastecimento?')">
      <input name="motivo_ignorar" placeholder="Motivo para ignorar, por exemplo: item de manutencao">
      <button class="danger" name="acao" value="ignorar">Ignorar esta pendencia</button>
    </form>
    <script>
    const vehicle=document.getElementById("pendingVehicle");
    const fuel=document.getElementById("pendingFuel");
    vehicle.addEventListener("change",()=>{{
      const value=vehicle.selectedOptions[0]?.dataset?.fuel||"";
      if(value==="flex"){{
        if(fuel.value!=="gasolina"&&fuel.value!=="etanol") fuel.value="gasolina";
      }} else if(["diesel_s10","diesel_500","gasolina","etanol"].includes(value)){{
        fuel.value=value;
      }}
    }});
    </script>
    """)


def _export_table(table, filename):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM {table} ORDER BY id DESC")
        rows = cur.fetchall()
        columns = [item[0] for item in cur.description]
    finally:
        conn.close()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(columns)
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
    )


@XML_BP.route("/estoque/exportar")
def exportar_estoque():
    return _export_table("importar_xml_estoque_itens", "estoque_itens")


@XML_BP.route("/abastecimentos/exportar")
def exportar_abastecimentos():
    return _export_table("importar_xml_abastecimentos", "abastecimentos_xml")


EMAIL_BASE = """
<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gestor de e-mails</title>
<style>
body{font-family:Arial;margin:0;background:#f4f4f4}header{background:#222;color:#fff;padding:15px}
nav a{color:#fff;margin-right:20px;text-decoration:none;line-height:2}.container{padding:20px}
.card{background:#fff;padding:20px;border-radius:8px;margin-bottom:20px}
input,select,textarea{width:100%;padding:8px;margin:6px 0 14px;box-sizing:border-box}
input[type=checkbox]{width:auto}button{padding:10px 18px;cursor:pointer}
table{width:100%;border-collapse:collapse;background:#fff}th,td{padding:10px;border-bottom:1px solid #ddd;text-align:left}
.scroll{overflow:auto}small{color:#666}.alert{background:#e8ffe8;padding:10px;margin-bottom:15px}
.email-row{cursor:pointer}.email-row:hover{background:#f0f6ff}.email-preview{display:block;max-width:620px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:5px}
.email-modal{position:fixed;inset:0;display:none;align-items:center;justify-content:center;padding:20px;background:rgba(0,0,0,.58);z-index:9999;box-sizing:border-box}
.email-modal.open{display:flex}.email-modal-card{background:#fff;border-radius:10px;width:min(1050px,96vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden}
.email-modal-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:18px 22px;border-bottom:1px solid #ddd}
.email-modal-head h3{margin:0}.email-modal-close{border:0;background:transparent;font-size:28px;line-height:1;padding:0 5px}
.email-modal-body{padding:18px 22px;overflow:auto}.email-meta{display:grid;grid-template-columns:140px 1fr;gap:7px 12px;margin-bottom:18px}
.email-content{border:1px solid #ddd;border-radius:7px;min-height:250px}.email-content iframe{display:block;width:100%;height:430px;border:0}
.email-content pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:16px;font:14px/1.5 Arial,sans-serif}.email-empty{padding:20px;color:#666}
.email-anexos{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.email-anexos a{padding:7px 10px;background:#eef4ff;border-radius:5px;text-decoration:none}
.email-headers{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f6f6;padding:12px;border-radius:6px}
@media(max-width:600px){.email-meta{grid-template-columns:1fr}.email-modal{padding:6px}.email-modal-body{padding:14px}.email-content iframe{height:55vh}}
</style>
</head>
<body><header><h2>Gestao de e-mails e anexos</h2><nav>
<a href="{{ url_for('gestor_emails.index') }}">Painel</a>
<a href="{{ url_for('gestor_emails.config') }}">Contas de e-mail</a>
<a href="{{ url_for('gestor_emails.fornecedores') }}">Fornecedores</a>
<a href="{{ url_for('gestor_emails.emails_page') }}">E-mails</a>
<a href="{{ url_for('gestor_emails.anexos_page') }}">Anexos</a>
<a href="{{ url_for('importar_xml.index') }}">Importar XML</a>
<a href="/">Sistema principal</a>
</nav></header><div class="container">
{% with messages = get_flashed_messages() %}{% for message in messages %}
<div class="alert">{{ message }}</div>{% endfor %}{% endwith %}
{{ body|safe }}</div></body></html>
"""


def _email_page(body):
    return render_template_string(EMAIL_BASE, body=body)


def _decode_text(value):
    if not value:
        return ""
    result = ""
    for text, encoding in decode_header(value):
        if isinstance(text, bytes):
            result += _decode_bytes_text(text, encoding)
        else:
            result += text
    return result.strip()


def _decode_bytes_text(payload, encoding=None):
    for candidate in (encoding, "utf-8", "latin-1"):
        if not candidate:
            continue
        try:
            return payload.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def _decode_message_payload(part):
    payload = part.get_payload(decode=True)
    if payload is None:
        raw_payload = part.get_payload()
        return raw_payload if isinstance(raw_payload, str) else ""
    return _decode_bytes_text(payload, part.get_content_charset())


def _extract_email_content(message):
    text_parts = []
    html_parts = []
    for part in message.walk():
        if part.is_multipart():
            continue
        if part.get_content_disposition() == "attachment" or part.get_filename():
            continue
        content_type = part.get_content_type().lower()
        if content_type not in {"text/plain", "text/html"}:
            continue
        content = _decode_message_payload(part).strip()
        if not content:
            continue
        if content_type == "text/html":
            html_parts.append(content)
        else:
            text_parts.append(content)

    raw_headers = "\n".join(
        f"{name}: {_decode_text(value)}" for name, value in message.items()
    )
    return {
        "body_text": "\n\n".join(text_parts),
        "body_html": "\n<hr>\n".join(html_parts),
        "raw_headers": raw_headers,
    }


def _email_preview(row):
    text = str(row.get("body_text") or "")
    if not text and row.get("body_html"):
        text = re.sub(r"<[^>]+>", " ", str(row["body_html"]))
        text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()[:220]


def _sanitize(value):
    value = _decode_text(str(value or ""))
    value = re.sub(r'[\\/*?:"<>|]', "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:120] if value else "sem_nome"


def _email_config():
    return _row("SELECT * FROM gestor_email_config WHERE id=1") or {}


def _normalize_search_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


SUPPLIER_CATEGORIES = {
    "materia_prima": "Fornecedor materia-prima",
    "pecas_auto": "Pecas auto / manutencao frota",
    "distribuidora": "Distribuidora",
    "outros": "Outros",
}


def _supplier_category(value):
    text = _normalize_search_text(value).replace("-", "_").replace(" ", "_")
    aliases = {
        "materia": "materia_prima",
        "materia_prima": "materia_prima",
        "fornecedor_materia_prima": "materia_prima",
        "pecas": "pecas_auto",
        "pecas_auto": "pecas_auto",
        "pecas_manutencao": "pecas_auto",
        "manutencao_frota": "pecas_auto",
        "auto": "pecas_auto",
        "distribuidor": "distribuidora",
        "distribuidora": "distribuidora",
        "outro": "outros",
        "outros": "outros",
    }
    return aliases.get(text, text if text in SUPPLIER_CATEGORIES else "outros")


def _supplier_category_label(value):
    return SUPPLIER_CATEGORIES.get(_supplier_category(value), SUPPLIER_CATEGORIES["outros"])


def _supplier_list_values(value):
    return [
        item.strip().lower()
        for item in re.split(r"[,;\n]+", str(value or ""))
        if item.strip()
    ]


def _email_domain(value):
    email_value = str(value or "").strip().lower()
    if "@" not in email_value:
        return ""
    return email_value.rsplit("@", 1)[-1].strip()


def _supplier_contact_fields(sender_email):
    email_value = str(sender_email or "").strip().lower()
    domain = _email_domain(email_value)
    return email_value, domain


def _supplier_contact_matches(row, sender_email):
    email_value, domain = _supplier_contact_fields(sender_email)
    if not email_value and not domain:
        return False
    emails = set(_supplier_list_values(row.get("emails")))
    domains = set(_supplier_list_values(row.get("dominios")))
    return bool((email_value and email_value in emails) or (domain and domain in domains))


def _supplier_append_value(current, value):
    value = str(value or "").strip().lower()
    values = _supplier_list_values(current)
    if value and value not in values:
        values.append(value)
    return "\n".join(values)


def _supplier_import_destination(supplier, cab=None, items=None):
    if _supplier_category((supplier or {}).get("categoria")) == "pecas_auto":
        try:
            if not eh_combustivel(cab or {}, items or []):
                return "manutencao"
        except Exception:
            return "manutencao"
    return ""


def _supplier_guess_category(name, sender_email=""):
    text = _normalize_search_text(f"{name} {sender_email}")
    if any(token in text for token in ("duas rodas", "saporiti")):
        return "materia_prima"
    if any(
        token in text
        for token in (
            "auto pec",
            "autopec",
            "pneu",
            "pneus",
            "lubrificante",
            "lubrificantes",
            "acumulador",
            "acumuladores",
            "rodoviario",
            "rodoviarios",
            "implemento",
            "implementos",
        )
    ):
        return "pecas_auto"
    if any(token in text for token in ("distribuidora", "distribuidor")):
        return "distribuidora"
    return "outros"


def _supplier_upsert_from_xml(cab, sender_email=""):
    cnpj = so_num((cab or {}).get("emitente_cnpj"))
    name = str((cab or {}).get("emitente_nome") or "").strip()
    email_value, domain = _supplier_contact_fields(sender_email)
    supplier = None
    if cnpj:
        supplier = _row(
            "SELECT * FROM gestor_email_fornecedores WHERE cnpj=%s LIMIT 1",
            (cnpj,),
        )
    if not supplier and (email_value or domain):
        rows = _rows(
            """
            SELECT *
            FROM gestor_email_fornecedores
            WHERE COALESCE(ativo, 1)=1
            ORDER BY id
            """
        )
        supplier = next(
            (row for row in rows if _supplier_contact_matches(row, sender_email)),
            None,
        )

    if supplier:
        updated_name = supplier.get("nome") or name
        updated_cnpj = supplier.get("cnpj") or cnpj or None
        updated_emails = _supplier_append_value(supplier.get("emails"), email_value)
        updated_domains = _supplier_append_value(supplier.get("dominios"), domain)
        updated_category = _supplier_category(supplier.get("categoria"))
        guessed_category = _supplier_guess_category(updated_name, sender_email)
        if updated_category == "outros" and guessed_category != "outros":
            updated_category = guessed_category
        _execute(
            """
            UPDATE gestor_email_fornecedores
            SET cnpj=%s, nome=%s, categoria=%s, emails=%s, dominios=%s, updated_at=%s
            WHERE id=%s
            """,
            (
                updated_cnpj,
                updated_name,
                updated_category,
                updated_emails,
                updated_domains,
                _now(),
                int(supplier["id"]),
            ),
        )
        supplier = dict(supplier)
        supplier.update(
            {
                "cnpj": updated_cnpj,
                "nome": updated_name,
                "categoria": updated_category,
                "emails": updated_emails,
                "dominios": updated_domains,
            }
        )
        return supplier

    supplier_id = _execute(
        """
        INSERT INTO gestor_email_fornecedores
            (cnpj, nome, categoria, emails, dominios, ativo, origem, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, 1, 'email_xml', %s, %s)
        """,
        (
            cnpj or None,
            name,
            _supplier_guess_category(name, sender_email),
            email_value,
            domain,
            _now(),
            _now(),
        ),
    )
    return _row(
        "SELECT * FROM gestor_email_fornecedores WHERE id=%s",
        (int(supplier_id),),
    ) or {
        "id": supplier_id,
        "cnpj": cnpj,
        "nome": name,
        "categoria": "outros",
        "emails": email_value,
        "dominios": domain,
    }


def _backfill_email_suppliers_from_xml(cur):
    try:
        cur.execute(
            """
            SELECT DISTINCT i.emitente_cnpj, i.emitente_nome, e.sender_email
            FROM importar_xml_estoque_itens i
            JOIN gestor_email_xml_importacoes x ON x.chave_nfe=i.chave_nfe
            JOIN gestor_email_anexos a ON a.id=x.attachment_id
            JOIN gestor_email_mensagens e ON e.id=a.email_id
            WHERE COALESCE(i.emitente_cnpj, '') <> ''
            UNION
            SELECT DISTINCT a2.posto_cnpj, a2.posto_nome, e.sender_email
            FROM importar_xml_abastecimentos a2
            JOIN gestor_email_xml_importacoes x ON x.chave_nfe=a2.chave_nfe
            JOIN gestor_email_anexos an ON an.id=x.attachment_id
            JOIN gestor_email_mensagens e ON e.id=an.email_id
            WHERE COALESCE(a2.posto_cnpj, '') <> ''
            UNION
            SELECT DISTINCT i.emitente_cnpj, i.emitente_nome, ''
            FROM importar_xml_estoque_itens i
            WHERE COALESCE(i.emitente_cnpj, '') <> ''
            UNION
            SELECT DISTINCT a2.posto_cnpj, a2.posto_nome, ''
            FROM importar_xml_abastecimentos a2
            WHERE COALESCE(a2.posto_cnpj, '') <> ''
            """
        )
        rows = cur.fetchall() or []
    except Exception:
        return
    for cnpj_raw, name_raw, email_raw in rows:
        cnpj = so_num(cnpj_raw)
        if not cnpj:
            continue
        name = str(name_raw or "").strip()
        email_value, domain = _supplier_contact_fields(email_raw)
        category = _supplier_guess_category(name, email_value)
        cur.execute(
            """
            INSERT INTO gestor_email_fornecedores
                (cnpj, nome, categoria, emails, dominios, ativo, origem, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 1, 'historico_xml', %s, %s)
            ON DUPLICATE KEY UPDATE
                nome=CASE
                    WHEN COALESCE(nome, '')='' THEN VALUES(nome)
                    ELSE nome
                END,
                categoria=CASE
                    WHEN COALESCE(categoria, 'outros')='outros'
                         AND VALUES(categoria)<>'outros' THEN VALUES(categoria)
                    ELSE categoria
                END,
                emails=CASE
                    WHEN VALUES(emails)='' THEN emails
                    WHEN COALESCE(emails, '')='' THEN VALUES(emails)
                    WHEN LOCATE(VALUES(emails), emails)=0 THEN CONCAT(emails, '\n', VALUES(emails))
                    ELSE emails
                END,
                dominios=CASE
                    WHEN VALUES(dominios)='' THEN dominios
                    WHEN COALESCE(dominios, '')='' THEN VALUES(dominios)
                    WHEN LOCATE(VALUES(dominios), dominios)=0 THEN CONCAT(dominios, '\n', VALUES(dominios))
                    ELSE dominios
                END,
                updated_at=VALUES(updated_at)
            """,
            (cnpj, name, category, email_value, domain, _now(), _now()),
        )
    try:
        cur.execute(
            """
            UPDATE gestor_email_xml_importacoes x
            JOIN importar_xml_estoque_itens i ON i.chave_nfe=x.chave_nfe
            JOIN gestor_email_fornecedores f ON f.cnpj=i.emitente_cnpj
            SET x.fornecedor_id=f.id,
                x.destino_importacao=CASE
                    WHEN f.categoria='pecas_auto' THEN 'manutencao'
                    ELSE 'estoque'
                END
            WHERE COALESCE(x.fornecedor_id, 0)=0
              OR COALESCE(x.destino_importacao, '')=''
            """
        )
        cur.execute(
            """
            UPDATE gestor_email_xml_importacoes x
            JOIN importar_xml_abastecimentos a ON a.chave_nfe=x.chave_nfe
            JOIN gestor_email_fornecedores f ON f.cnpj=a.posto_cnpj
            SET x.fornecedor_id=f.id,
                x.destino_importacao='abastecimento'
            WHERE COALESCE(x.fornecedor_id, 0)=0
              OR COALESCE(x.destino_importacao, '')=''
            """
        )
    except Exception:
        pass


def _backfill_auto_parts_maintenance(conn):
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT i.*, f.id AS fornecedor_id, f.nome AS fornecedor_nome
            FROM importar_xml_estoque_itens i
            JOIN gestor_email_xml_importacoes x ON x.chave_nfe=i.chave_nfe
            JOIN gestor_email_fornecedores f ON f.id=x.fornecedor_id
            WHERE f.categoria='pecas_auto'
              AND COALESCE(i.chave_nfe, '') <> ''
            ORDER BY i.chave_nfe, i.id
            """
        )
        rows = cur.fetchall() or []
    except Exception:
        return
    grouped = {}
    for row in rows:
        grouped.setdefault(row.get("chave_nfe"), []).append(row)
    for chave, items in grouped.items():
        first = items[0]
        item_rows = [
            {
                "item_seq": index,
                "codigo_produto_nfe": item.get("codigo_produto") or "",
                "codigo_barras": "",
                "nome_produto": item.get("descricao_produto") or "",
                "unidade": item.get("unidade") or "",
                "quantidade": item.get("quantidade") or 0,
                "valor_unitario": item.get("valor_unitario") or 0,
                "valor_total": item.get("valor_total_item") or 0,
            }
            for index, item in enumerate(items, start=1)
        ]
        valor = sum(float(item.get("valor_total") or 0) for item in item_rows)
        motivo = (
            "Nota direcionada para manutencao da frota pelo cadastro do fornecedor "
            f"{str(first.get('fornecedor_nome') or first.get('emitente_nome') or '').strip()}."
        )
        cur.execute(
            """
            SELECT id, status
            FROM manutencao_xml_pre_lancamentos
            WHERE nota_key=%s
            LIMIT 1
            """,
            (chave,),
        )
        current = cur.fetchone() or {}
        if str(current.get("status") or "") == "confirmado":
            continue
        cur.execute(
            """
            INSERT INTO manutencao_xml_pre_lancamentos (
                nota_key, importar_xml_abastecimento_id, chave_nfe,
                numero_nota, veiculo_id, placa_xml, sugestao_confianca,
                origem_veiculo, status, motivo, emitente_nome,
                data_documento, km, valor, itens_json, criado_em, atualizado_em
            )
            VALUES (
                %s, NULL, %s, %s, NULL, '', 0, 'cadastro_fornecedor',
                'pendente', %s, %s, %s, 0, %s, %s, NOW(), NOW()
            )
            ON DUPLICATE KEY UPDATE
                origem_veiculo=VALUES(origem_veiculo),
                status=CASE
                    WHEN status='confirmado' THEN status
                    ELSE 'pendente'
                END,
                motivo=VALUES(motivo),
                emitente_nome=VALUES(emitente_nome),
                data_documento=VALUES(data_documento),
                valor=VALUES(valor),
                itens_json=VALUES(itens_json),
                atualizado_em=NOW()
            """,
            (
                chave,
                chave,
                str(first.get("numero_nota") or "")[:120],
                motivo[:500],
                str(first.get("emitente_nome") or "")[:255],
                _nfe_document_date(first.get("data_emissao")),
                valor,
                json.dumps(item_rows, ensure_ascii=False),
            ),
        )
        cur.execute(
            """
            UPDATE gestor_email_xml_importacoes
            SET tipo_detectado='MANUTENCAO',
                destino_importacao='manutencao'
            WHERE chave_nfe=%s
              AND fornecedor_id=%s
            """,
            (chave, int(first.get("fornecedor_id") or 0)),
        )


def _refresh_supplier_import_routes():
    conn = _conn()
    try:
        _backfill_auto_parts_maintenance(conn)
        conn.commit()
    finally:
        conn.close()


def _email_account_id(config):
    try:
        return int((config or {}).get("id") or (config or {}).get("account_id") or 1)
    except (TypeError, ValueError):
        return 1


def _email_protocol(config):
    return str((config or {}).get("protocol") or "pop3").strip().lower() or "pop3"


def _email_account_label(config):
    label = str((config or {}).get("account_name") or "").strip()
    if label:
        return label[:120]
    user = str((config or {}).get("email_user") or "").strip()
    return (user or "Principal")[:120]


def _email_account_enabled(config):
    if "enabled" not in (config or {}):
        return True
    return bool(int((config or {}).get("enabled") or 0))


def _email_account_configured(config):
    return bool(
        _email_account_enabled(config)
        and (config or {}).get("pop_host")
        and (config or {}).get("email_user")
        and (config or {}).get("email_pass")
    )


def _email_accounts(account_ids=None):
    ids_filter = None
    if account_ids:
        ids_filter = {
            int(value)
            for value in account_ids
            if str(value).strip().isdigit()
        }
    try:
        rows = _rows(
            """
            SELECT *
            FROM gestor_email_config
            WHERE COALESCE(enabled, 1)=1
            ORDER BY id
            """
        )
    except RuntimeError:
        config = _email_config()
        rows = [config] if config else []
    if ids_filter is not None:
        rows = [row for row in rows if _email_account_id(row) in ids_filter]
    return [row for row in rows if _email_account_configured(row)]


def _email_uid_key(config, uid, mailbox=None):
    uid = str(uid or "").strip()
    if _email_account_id(config) == 1 and _email_protocol(config) == "pop3":
        return uid
    primary_mailbox = str((config or {}).get("mailbox") or "INBOX").strip()
    current_mailbox = str(mailbox or primary_mailbox).strip()
    if (
        _email_protocol(config) == "imap"
        and current_mailbox
        and current_mailbox.upper() != primary_mailbox.upper()
    ):
        return (
            f"acct:{_email_account_id(config)}:{_email_protocol(config)}:"
            f"{_sanitize(current_mailbox)}:{uid}"
        )
    return f"acct:{_email_account_id(config)}:{_email_protocol(config)}:{uid}"


def _email_filter_keywords(config):
    raw = str((config or {}).get("filter_keywords") or "").strip()
    return [
        value.strip()
        for value in re.split(r"[,;\n]+", raw)
        if value.strip()
    ]


def _email_message_has_xml_payload(message):
    for spec in _email_attachment_specs(message):
        suffix = Path(str(spec.get("filename") or "")).suffix.lower()
        if suffix in {".xml", ".zip"}:
            return True
    return False


def _email_message_matches_account_filter(
    message,
    config,
    force_xml_attachments=False,
):
    if force_xml_attachments and _email_message_has_xml_payload(message):
        return True, "anexo xml/zip"

    keywords = _email_filter_keywords(config)
    if not keywords:
        return True, ""

    content = _extract_email_content(message)
    attachment_names = " ".join(
        str(spec.get("filename") or "")
        for spec in _email_attachment_specs(message)
    )
    haystack = _normalize_search_text(
        " ".join(
            [
                _decode_text(message.get("From", "")),
                _decode_text(message.get("To", "")),
                _decode_text(message.get("Subject", "")),
                content.get("body_text") or "",
                re.sub(r"<[^>]+>", " ", content.get("body_html") or ""),
                attachment_names,
            ]
        )
    )
    matched = [
        keyword
        for keyword in keywords
        if _normalize_search_text(keyword) in haystack
    ]
    return bool(matched), ", ".join(matched[:8])


def _runtime_environment():
    value = (
        os.environ.get("RB_ENV")
        or os.environ.get("APP_ENV")
        or "homologacao"
    )
    normalized = re.sub(r"[^a-z]", "", str(value).strip().lower())
    return "producao" if normalized in {"prod", "production", "producao"} else "homologacao"


def _delete_from_server_enabled():
    if _runtime_environment() != "producao":
        return False
    value = str(os.environ.get("RB_EMAIL_DELETE_FROM_SERVER", "0")).strip().lower()
    return value not in {"0", "false", "nao", "no", "off", "disabled"}


def _delete_policy_description():
    environment = _runtime_environment()
    if environment != "producao":
        return (
            "Homologacao: os e-mails permanecem no servidor, mesmo depois "
            "de armazenados localmente."
        )
    if _delete_from_server_enabled():
        return (
            "Producao: exclusao de POP3 habilitada por ambiente; contas IMAP "
            "permanecem sempre no servidor."
        )
    return (
        "Producao: a exclusao de e-mails esta desativada pela variavel "
        "RB_EMAIL_DELETE_FROM_SERVER."
    )


def _email_scheduler_enabled():
    if _runtime_environment() != "producao":
        return False
    value = str(os.environ.get("RB_EMAIL_AUTO_IMPORT", "1")).strip().lower()
    return value not in {"0", "false", "nao", "no", "off", "disabled"}


def _email_scheduler_description():
    if not _email_scheduler_enabled():
        return "Agendador automatico desativado neste ambiente."
    config = _email_schedule_config()
    day_names = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
    days = ", ".join(day_names[day] for day in sorted(config["days"]))
    return (
        f"Producao: verificacao automatica a cada "
        f"{config['interval_minutes']} minuto(s), das "
        f"{config['start'].strftime('%H:%M')} as "
        f"{config['end'].strftime('%H:%M')}, dias da semana "
        f"{days}, fuso {config['timezone_name']}."
    )


def _email_schedule_config():
    start_text = str(os.environ.get("RB_EMAIL_BUSINESS_START", "08:00")).strip()
    end_text = str(os.environ.get("RB_EMAIL_BUSINESS_END", "18:00")).strip()
    try:
        start_time = datetime.strptime(start_text, "%H:%M").time()
        end_time = datetime.strptime(end_text, "%H:%M").time()
    except ValueError as exc:
        raise ValueError("horario comercial deve usar o formato HH:MM") from exc
    days = {
        int(value.strip())
        for value in str(
            os.environ.get("RB_EMAIL_BUSINESS_DAYS", "0,1,2,3,4")
        ).split(",")
        if value.strip().isdigit() and 0 <= int(value.strip()) <= 6
    }
    if not days:
        days = {0, 1, 2, 3, 4}
    timezone_name = str(
        os.environ.get("RB_EMAIL_TIMEZONE", "America/Sao_Paulo")
    ).strip()
    return {
        "interval_minutes": max(
            1,
            int(os.environ.get("RB_EMAIL_AUTO_INTERVAL_MINUTES", "5")),
        ),
        "max_emails": max(
            1,
            int(os.environ.get("RB_EMAIL_AUTO_MAX_EMAILS", "200")),
        ),
        "start": start_time,
        "end": end_time,
        "days": days,
        "timezone": ZoneInfo(timezone_name),
        "timezone_name": timezone_name,
    }


def _email_schedule_now(config=None):
    config = config or _email_schedule_config()
    return datetime.now(config["timezone"])


def _email_is_business_time(moment=None, config=None):
    config = config or _email_schedule_config()
    moment = moment or _email_schedule_now(config)
    current_time = moment.timetz().replace(tzinfo=None)
    return (
        moment.weekday() in config["days"]
        and config["start"] <= current_time < config["end"]
    )


def _email_next_business_run(moment=None, config=None):
    config = config or _email_schedule_config()
    moment = moment or _email_schedule_now(config)
    if _email_is_business_time(moment, config):
        return moment
    for offset in range(0, 8):
        day = moment.date() + timedelta(days=offset)
        candidate = datetime.combine(
            day,
            config["start"],
            tzinfo=config["timezone"],
        )
        if candidate.weekday() not in config["days"]:
            continue
        if candidate > moment:
            return candidate
    return moment


def _email_scheduler_claim(config, moment=None):
    moment = moment or _email_schedule_now(config)
    now_epoch = int(moment.timestamp())
    interval_seconds = config["interval_minutes"] * 60
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        conn.start_transaction()
        cur.execute(
            """
            INSERT IGNORE INTO service_scheduler_state
                (name, last_run_epoch, updated_at)
            VALUES ('gestor_email', 0, %s)
            """,
            (_now(),),
        )
        cur.execute(
            """
            SELECT last_run_epoch
            FROM service_scheduler_state
            WHERE name='gestor_email'
            FOR UPDATE
            """
        )
        last_run = int((cur.fetchone() or {}).get("last_run_epoch") or 0)
        if last_run and now_epoch - last_run < interval_seconds:
            conn.rollback()
            return False
        cur.execute(
            """
            UPDATE service_scheduler_state
            SET last_run_epoch=%s, updated_at=%s
            WHERE name='gestor_email'
            """,
            (now_epoch, _now()),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _attachment_path(relative):
    root = Path(_email_attachment_dir).resolve()
    candidate = (root / str(relative or "")).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Caminho de anexo invalido.")
    return candidate


def _storage_used_bytes():
    root = Path(_email_attachment_dir)
    if not root.is_dir():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _connect_pop3(config):
    cls = poplib.POP3_SSL if config.get("use_ssl") else poplib.POP3
    server = cls(config["pop_host"], int(config["pop_port"]), timeout=60)
    server.user(config["email_user"])
    server.pass_(config["email_pass"])
    return server


def _connect_imap(config):
    cls = imaplib.IMAP4_SSL if config.get("use_ssl") else imaplib.IMAP4
    try:
        timeout = max(60, int(os.environ.get("RB_EMAIL_IMAP_TIMEOUT", "180")))
    except ValueError:
        timeout = 180
    server = cls(config["pop_host"], int(config["pop_port"]), timeout=timeout)
    server.login(config["email_user"], config["email_pass"])
    return server


def _pop_uid(server, index):
    result = server.uidl(index)
    data = result[1] if isinstance(result, tuple) else result
    if isinstance(data, list):
        data = data[0]
    if isinstance(data, bytes):
        data = data.decode(errors="ignore")
    return str(data).split()[-1]


def _imap_since_criterion(config):
    value = str((config or {}).get("since_date") or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%d/%m/%Y")
        except ValueError:
            return None
    return parsed.strftime("%d-%b-%Y")


def _parse_email_date(value):
    value = str(value or "").strip()
    if not value:
        return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def _email_today():
    timezone_name = os.environ.get("RB_EMAIL_TIMEZONE", "America/Sao_Paulo")
    try:
        timezone = ZoneInfo(timezone_name)
    except Exception:
        timezone = ZoneInfo("America/Sao_Paulo")
    return datetime.now(timezone).date()


def _imap_before_criterion(until_date=None):
    parsed = _parse_email_date(until_date) or _email_today()
    exclusive = parsed + timedelta(days=1)
    return exclusive.strftime("%d-%b-%Y")


def _imap_list_mailbox_name(item):
    text = item.decode("utf-8", "replace") if isinstance(item, bytes) else str(item)
    match = re.search(r'"([^"]+)"\s*$', text)
    if match:
        name = match.group(1)
    else:
        name = text.rsplit(" ", 1)[-1].strip('"')
    flags = text.split(")", 1)[0].strip(" (").lower()
    return flags, name


def _imap_history_mailboxes(server, config):
    raw = str(os.environ.get("RB_EMAIL_BOL_HISTORY_MAILBOXES", "")).strip()
    primary = str((config or {}).get("mailbox") or "INBOX").strip() or "INBOX"
    if not raw:
        return [primary]
    requested = [
        item.strip()
        for item in re.split(r"[,;\n]+", raw)
        if item.strip()
    ]
    if not any(item.upper() == "ALL" for item in requested):
        mailboxes = [primary, *requested]
    else:
        status, folders = server.list()
        if status != "OK":
            return [primary]
        mailboxes = [primary]
        for item in folders or []:
            flags, name = _imap_list_mailbox_name(item)
            if not name:
                continue
            if any(flag in flags for flag in ("\\noselect", "\\trash", "\\junk", "\\drafts")):
                continue
            if _normalize_search_text(name) in {"quarentena", "spam", "lixeira"}:
                continue
            mailboxes.append(name)

    seen = set()
    unique = []
    for mailbox in mailboxes:
        key = mailbox.upper()
        if key in seen:
            continue
        seen.add(key)
        unique.append(mailbox)
    return unique


def _imap_mailbox_arg(mailbox):
    value = str(mailbox or "INBOX").strip() or "INBOX"
    if value.startswith('"') and value.endswith('"'):
        return value
    if re.search(r'\s|["\\\\]', value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _imap_close_quietly(server):
    if not server:
        return
    try:
        unselect = getattr(server, "unselect", None)
        if callable(unselect):
            unselect()
    except Exception:
        pass
    try:
        server.logout()
    except Exception:
        pass


def _imap_reopen_mailbox(config, server, mailbox):
    _imap_close_quietly(server)
    server = _connect_imap(config)
    try:
        status, _ = server.select(_imap_mailbox_arg(mailbox), readonly=True)
    except Exception:
        _imap_close_quietly(server)
        raise
    if status != "OK":
        _imap_close_quietly(server)
        raise RuntimeError(f"Nao foi possivel reabrir a caixa IMAP {mailbox}.")
    return server


def _imap_fetch_message(server, message_id):
    status, payload = server.fetch(message_id, "(UID BODY.PEEK[])")
    if status != "OK":
        return None, None
    raw_message = None
    raw_uid = None
    for item in payload or []:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        metadata = item[0].decode(errors="ignore") if isinstance(item[0], bytes) else str(item[0])
        match = re.search(r"\bUID\s+(\d+)", metadata)
        if match:
            raw_uid = match.group(1)
        raw_message = item[1]
        break
    if not raw_message:
        return None, None
    return raw_uid or str(message_id.decode() if isinstance(message_id, bytes) else message_id), email.message_from_bytes(raw_message)


def _imap_fetch_message_with_retry(config, server, mailbox, message_id):
    current_server = server
    last_error = None
    for attempt in range(2):
        if attempt:
            try:
                current_server = _imap_reopen_mailbox(
                    config,
                    current_server,
                    mailbox,
                )
            except Exception as exc:
                return None, None, None, exc
        try:
            raw_uid, message = _imap_fetch_message(current_server, message_id)
        except Exception as exc:
            last_error = exc
            continue
        if message:
            return current_server, raw_uid, message, None
        last_error = RuntimeError("Resposta IMAP sem conteudo da mensagem.")
    return current_server, None, None, last_error


def _email_attachment_specs(message):
    specs = []
    for part in message.walk():
        if part.get_content_disposition() != "attachment" and not part.get_filename():
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        specs.append(
            {
                "filename": _sanitize(part.get_filename() or "anexo"),
                "payload": payload,
                "size_bytes": len(payload),
            }
        )
    return specs


def _email_xml_trusted_senders():
    raw = os.environ.get(
        "RB_EMAIL_XML_TRUSTED_SENDERS",
        "bebidasriobranco8@gmail.com",
    )
    return {
        value.strip().lower()
        for value in re.split(r"[,;\n]+", str(raw or ""))
        if value.strip()
    }


def _email_xml_limits(sender_email=""):
    max_entries = max(
        1,
        int(os.environ.get("RB_EMAIL_XML_ZIP_MAX_ENTRIES", "200")),
    )
    if str(sender_email or "").strip().lower() in _email_xml_trusted_senders():
        max_entries = max(
            max_entries,
            int(
                os.environ.get(
                    "RB_EMAIL_XML_TRUSTED_ZIP_MAX_ENTRIES",
                    "1000",
                )
            ),
        )
    return {
        "max_entries": max_entries,
        "max_file_bytes": max(
            1024,
            int(os.environ.get("RB_EMAIL_XML_MAX_FILE_MB", "20"))
            * 1024
            * 1024,
        ),
        "max_total_bytes": max(
            1024,
            int(os.environ.get("RB_EMAIL_XML_ZIP_MAX_TOTAL_MB", "100"))
            * 1024
            * 1024,
        ),
    }


def _email_xml_tracking(
    attachment_id,
    source_name,
    content_sha256,
    status,
    fornecedor_id=None,
    destino_importacao="",
    chave_nfe="",
    tipo_detectado="",
    registros=0,
    mensagem="",
):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO gestor_email_xml_importacoes (
                attachment_id, source_name, content_sha256, fornecedor_id,
                destino_importacao, chave_nfe, status, tipo_detectado,
                registros, mensagem,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                fornecedor_id=VALUES(fornecedor_id),
                destino_importacao=VALUES(destino_importacao),
                chave_nfe=VALUES(chave_nfe),
                status=VALUES(status),
                tipo_detectado=VALUES(tipo_detectado),
                registros=VALUES(registros),
                mensagem=VALUES(mensagem),
                updated_at=VALUES(updated_at)
            """,
            (
                int(attachment_id),
                str(source_name or "anexo.xml")[:512],
                content_sha256,
                int(fornecedor_id or 0) or None,
                str(destino_importacao or "")[:40],
                str(chave_nfe or "")[:80],
                str(status or "ERRO")[:40],
                str(tipo_detectado or "")[:40],
                int(registros or 0),
                str(mensagem or "")[:2000],
                _now(),
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _email_xml_tracking_existing(attachment_id, source_name, content_sha256):
    return _row(
        """
        SELECT *
        FROM gestor_email_xml_importacoes
        WHERE attachment_id=%s AND source_name=%s AND content_sha256=%s
        LIMIT 1
        """,
        (int(attachment_id), str(source_name or "anexo.xml")[:512], content_sha256),
    )


def _email_xml_already_imported(chave_nfe, content_sha256):
    tracked = _row(
        """
        SELECT id
        FROM gestor_email_xml_importacoes
        WHERE content_sha256=%s
          AND status IN ('IMPORTADO', 'JA_IMPORTADO')
        LIMIT 1
        """,
        (content_sha256,),
    )
    if tracked:
        return True
    chave = so_num(chave_nfe)
    if not chave:
        return False
    existing = _row(
        """
        SELECT chave_nfe
        FROM importar_xml_abastecimentos
        WHERE chave_nfe=%s
        LIMIT 1
        """,
        (chave,),
    )
    if existing:
        return True
    existing = _row(
        """
        SELECT chave_nfe
        FROM importar_xml_estoque_itens
        WHERE chave_nfe=%s
        LIMIT 1
        """,
        (chave,),
    )
    if existing:
        return True
    try:
        existing = _row(
            """
            SELECT chave_nfe
            FROM manutencao_xml_pre_lancamentos
            WHERE chave_nfe=%s
              AND status IN ('pendente', 'confirmado')
            LIMIT 1
            """,
            (chave,),
        )
        return bool(existing)
    except Exception:
        return False


def _nfe_document_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    return text[:10]


def _maintenance_xml_nota_key(cab):
    chave = so_num((cab or {}).get("chave_nfe"))
    if len(chave) == 44:
        return chave
    parts = [
        so_num((cab or {}).get("emitente_cnpj")),
        str((cab or {}).get("numero_nota") or "").strip(),
        _nfe_document_date((cab or {}).get("data_emissao")) or "",
    ]
    return "|".join(parts)


def _maintenance_items_from_nfe(items):
    normalized = []
    for index, item in enumerate(items or [], start=1):
        normalized.append(
            {
                "item_seq": item.get("nItem") or item.get("item_seq") or index,
                "codigo_produto_nfe": item.get("codigo_produto") or "",
                "codigo_barras": item.get("codigo_barras") or "",
                "nome_produto": item.get("descricao_produto") or "",
                "unidade": item.get("unidade") or "",
                "quantidade": item.get("quantidade") or 0,
                "valor_unitario": item.get("valor_unitario") or 0,
                "valor_total": item.get("valor_total_item") or 0,
            }
        )
    return normalized


def _email_import_maintenance_xml(cab, items, supplier=None):
    nota_key = _maintenance_xml_nota_key(cab)
    chave = so_num((cab or {}).get("chave_nfe"))
    item_rows = _maintenance_items_from_nfe(items)
    valor = sum(float(item.get("valor_total") or 0) for item in item_rows)
    motivo = (
        "Nota direcionada para manutencao da frota pelo cadastro do fornecedor "
        f"{str((supplier or {}).get('nome') or (cab or {}).get('emitente_nome') or '').strip()}."
    )
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT id, status
            FROM manutencao_xml_pre_lancamentos
            WHERE nota_key=%s
            LIMIT 1
            """,
            (nota_key,),
        )
        current = cur.fetchone() or {}
        if str(current.get("status") or "") == "confirmado":
            return True, 0, "Pre-lancamento de manutencao ja confirmado."
        cur.execute(
            """
            INSERT INTO manutencao_xml_pre_lancamentos (
                nota_key, importar_xml_abastecimento_id, chave_nfe,
                numero_nota, veiculo_id, placa_xml, sugestao_confianca,
                origem_veiculo, status, motivo, emitente_nome,
                data_documento, km, valor, itens_json, criado_em, atualizado_em
            )
            VALUES (
                %s, NULL, %s, %s, NULL, '', 0, 'cadastro_fornecedor',
                'pendente', %s, %s, %s, 0, %s, %s, NOW(), NOW()
            )
            ON DUPLICATE KEY UPDATE
                chave_nfe=VALUES(chave_nfe),
                numero_nota=VALUES(numero_nota),
                origem_veiculo=VALUES(origem_veiculo),
                status=CASE
                    WHEN status='confirmado' THEN status
                    ELSE 'pendente'
                END,
                motivo=VALUES(motivo),
                emitente_nome=VALUES(emitente_nome),
                data_documento=VALUES(data_documento),
                valor=VALUES(valor),
                itens_json=VALUES(itens_json),
                atualizado_em=NOW()
            """,
            (
                nota_key,
                chave,
                str((cab or {}).get("numero_nota") or "")[:120],
                motivo[:500],
                str((cab or {}).get("emitente_nome") or "")[:255],
                _nfe_document_date((cab or {}).get("data_emissao")),
                valor,
                json.dumps(item_rows, ensure_ascii=False),
            ),
        )
        conn.commit()
        return True, len(item_rows), "XML enviado para pre-lancamento de manutencao da frota."
    except Exception as exc:
        conn.rollback()
        return False, 0, str(exc)
    finally:
        conn.close()


def _email_import_xml_bytes(attachment_id, source_name, payload, sender_email=""):
    content_sha256 = hashlib.sha256(payload).hexdigest()
    tracked = _email_xml_tracking_existing(
        attachment_id,
        source_name,
        content_sha256,
    )
    if tracked and tracked.get("status") in {"IMPORTADO", "JA_IMPORTADO"}:
        return {
            "ok": True,
            "status": tracked["status"],
            "tipo": tracked.get("tipo_detectado") or "",
            "registros": int(tracked.get("registros") or 0),
            "mensagem": tracked.get("mensagem") or "",
        }

    limits = _email_xml_limits()
    if not payload or len(payload) > limits["max_file_bytes"]:
        message = "XML vazio ou acima do limite permitido."
        _email_xml_tracking(
            attachment_id,
            source_name,
            content_sha256,
            "ERRO",
            mensagem=message,
        )
        return {"ok": False, "status": "ERRO", "mensagem": message}

    Path(_xml_upload_dir).mkdir(parents=True, exist_ok=True)
    safe_name = secure_filename(Path(source_name).name) or "anexo.xml"
    if not safe_name.lower().endswith(".xml"):
        safe_name += ".xml"
    path = Path(_xml_upload_dir) / f"email_{attachment_id}_{uuid.uuid4().hex}_{safe_name}"
    try:
        path.write_bytes(payload)
        cab, items = parse_nfe(path)
        chave_nfe = so_num(cab.get("chave_nfe"))
        supplier = _supplier_upsert_from_xml(cab, sender_email=sender_email)
        supplier_id = int((supplier or {}).get("id") or 0) or None
        destination = _supplier_import_destination(supplier, cab, items)
        tipo = "ABASTECIMENTO" if eh_combustivel(cab, items) else "ESTOQUE"
        if destination == "manutencao":
            tipo = "MANUTENCAO"
        if _email_xml_already_imported(chave_nfe, content_sha256):
            _email_xml_tracking(
                attachment_id,
                source_name,
                content_sha256,
                "JA_IMPORTADO",
                fornecedor_id=supplier_id,
                destino_importacao=destination or tipo.lower(),
                chave_nfe=chave_nfe,
                tipo_detectado=tipo,
                mensagem="NF-e ja existente no ImportaXml; nenhuma duplicacao criada.",
            )
            return {
                "ok": True,
                "status": "JA_IMPORTADO",
                "tipo": tipo,
                "registros": 0,
                "mensagem": "NF-e ja existente no ImportaXml.",
            }

        if destination == "manutencao":
            success, count, message = _email_import_maintenance_xml(
                cab,
                items,
                supplier=supplier,
            )
            kind = "MANUTENCAO"
        else:
            success, kind, count, message = _import_xml_file(path, safe_name)
        status = "IMPORTADO" if success else "ERRO"
        _email_xml_tracking(
            attachment_id,
            source_name,
            content_sha256,
            status,
            fornecedor_id=supplier_id,
            destino_importacao=destination or str(kind or tipo).lower(),
            chave_nfe=chave_nfe,
            tipo_detectado=kind if success else tipo,
            registros=count if success else 0,
            mensagem=message,
        )
        return {
            "ok": bool(success),
            "status": status,
            "tipo": kind if success else tipo,
            "registros": count if success else 0,
            "mensagem": message,
        }
    except Exception as exc:
        message = str(exc)
        _email_xml_tracking(
            attachment_id,
            source_name,
            content_sha256,
            "ERRO",
            mensagem=message,
        )
        return {"ok": False, "status": "ERRO", "mensagem": message}


def _email_track_zip_error(attachment_id, source_name, message, fingerprint_parts):
    content_sha256 = hashlib.sha256(
        "|".join(str(part) for part in fingerprint_parts).encode("utf-8", "replace")
    ).hexdigest()
    _email_xml_tracking(
        attachment_id,
        source_name,
        content_sha256,
        "ERRO",
        mensagem=message,
    )


def _email_import_xml_attachment(attachment, sender_email=""):
    filename = str(attachment.get("filename") or "")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xml", ".zip"}:
        return {"relevant": False, "ok": True, "results": []}
    try:
        path = _attachment_path(attachment.get("path_relativo"))
    except ValueError as exc:
        return {
            "relevant": True,
            "ok": False,
            "results": [{"ok": False, "status": "ERRO", "mensagem": str(exc)}],
        }
    if not path.is_file():
        return {
            "relevant": True,
            "ok": False,
            "results": [
                {
                    "ok": False,
                    "status": "ERRO",
                    "mensagem": f"Anexo local nao encontrado: {filename}",
                }
            ],
        }

    if suffix == ".xml":
        result = _email_import_xml_bytes(
            attachment["id"],
            filename,
            path.read_bytes(),
            sender_email=sender_email,
        )
        return {"relevant": True, "ok": result["ok"], "results": [result]}

    limits = _email_xml_limits(sender_email)
    results = []
    try:
        with zipfile.ZipFile(path) as archive:
            xml_entries = [
                info
                for info in archive.infolist()
                if not info.is_dir() and Path(info.filename).suffix.lower() == ".xml"
            ]
            if len(xml_entries) > limits["max_entries"]:
                raise ValueError("ZIP possui mais XMLs que o limite permitido.")
            total_size = sum(max(0, info.file_size) for info in xml_entries)
            if total_size > limits["max_total_bytes"]:
                raise ValueError("ZIP excede o limite total de XMLs permitido.")
            for info in xml_entries:
                if info.flag_bits & 0x1:
                    message = f"XML protegido por senha no ZIP: {info.filename}"
                    source_name = f"{filename}::{info.filename}"
                    _email_track_zip_error(
                        attachment["id"],
                        source_name,
                        message,
                        (
                            attachment["id"],
                            source_name,
                            info.CRC,
                            info.file_size,
                            "encrypted",
                        ),
                    )
                    results.append({"ok": False, "status": "ERRO", "mensagem": message})
                    continue
                if info.file_size > limits["max_file_bytes"]:
                    message = f"XML acima do limite no ZIP: {info.filename}"
                    source_name = f"{filename}::{info.filename}"
                    _email_track_zip_error(
                        attachment["id"],
                        source_name,
                        message,
                        (
                            attachment["id"],
                            source_name,
                            info.CRC,
                            info.file_size,
                            "too-large",
                        ),
                    )
                    results.append({"ok": False, "status": "ERRO", "mensagem": message})
                    continue
                results.append(
                    _email_import_xml_bytes(
                        attachment["id"],
                        f"{filename}::{info.filename}",
                        archive.read(info),
                        sender_email=sender_email,
                    )
                )
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        message = str(exc)
        try:
            fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            fingerprint = str(path)
        _email_track_zip_error(
            attachment["id"],
            filename,
            message,
            (attachment["id"], filename, fingerprint, "zip-error"),
        )
        results.append({"ok": False, "status": "ERRO", "mensagem": message})
    return {
        "relevant": True,
        "ok": all(result.get("ok") for result in results),
        "results": results,
    }


def _email_import_xml_attachments(email_id):
    email_data = _row(
        """
        SELECT sender_email
        FROM gestor_email_mensagens
        WHERE id=%s
        """,
        (int(email_id),),
    ) or {}
    sender_email = str(email_data.get("sender_email") or "").strip().lower()
    attachments = _rows(
        """
        SELECT id, email_id, filename, path_relativo, size_bytes
        FROM gestor_email_anexos
        WHERE email_id=%s
        ORDER BY id
        """,
        (int(email_id),),
    )
    imported = existing = errors = relevant = 0
    messages = []
    for attachment in attachments:
        outcome = _email_import_xml_attachment(
            attachment,
            sender_email=sender_email,
        )
        if not outcome["relevant"]:
            continue
        relevant += 1
        for result in outcome["results"]:
            status = result.get("status")
            if status == "IMPORTADO":
                imported += 1
            elif status == "JA_IMPORTADO":
                existing += 1
            elif not result.get("ok"):
                errors += 1
                if result.get("mensagem"):
                    messages.append(result["mensagem"])
    return {
        "ok": errors == 0,
        "relevant_attachments": relevant,
        "imported": imported,
        "existing": existing,
        "errors": errors,
        "message": "; ".join(messages[:5]),
    }


def _email_import_pending_local_attachments(max_attachments=None, account_ids=None):
    if max_attachments is None:
        max_attachments = max(
            1,
            int(
                os.environ.get(
                    "RB_EMAIL_XML_LOCAL_BACKLOG_MAX_ATTACHMENTS",
                    "200",
                )
            ),
        )
    params = []
    account_clause = ""
    if account_ids:
        ids_filter = [
            int(value)
            for value in account_ids
            if str(value).strip().isdigit()
        ]
        if ids_filter:
            placeholders = ", ".join(["%s"] * len(ids_filter))
            account_clause = f" AND COALESCE(e.account_id, 1) IN ({placeholders})"
            params.extend(ids_filter)

    limit_clause = ""
    if int(max_attachments or 0) > 0:
        limit_clause = "LIMIT %s"
        params.append(int(max_attachments))

    attachments = _rows(
        f"""
        SELECT
            a.id,
            a.email_id,
            a.filename,
            a.path_relativo,
            a.size_bytes,
            LOWER(COALESCE(e.sender_email, '')) AS sender_email
        FROM gestor_email_anexos a
        JOIN gestor_email_mensagens e ON e.id=a.email_id
        WHERE (
            LOWER(COALESCE(a.filename, '')) LIKE '%%.xml'
            OR LOWER(COALESCE(a.filename, '')) LIKE '%%.zip'
        )
          AND (
            NOT EXISTS (
                SELECT 1
                FROM gestor_email_xml_importacoes x
                WHERE x.attachment_id=a.id
                  AND x.status IN ('IMPORTADO', 'JA_IMPORTADO')
            )
            OR EXISTS (
                SELECT 1
                FROM gestor_email_xml_importacoes x
                WHERE x.attachment_id=a.id
                  AND x.status='ERRO'
            )
          )
          {account_clause}
        ORDER BY a.id
        {limit_clause}
        """,
        tuple(params),
    )
    trusted = _email_xml_trusted_senders()
    attachments.sort(
        key=lambda item: (
            0 if str(item.get("sender_email") or "").lower() in trusted else 1,
            int(item.get("id") or 0),
        )
    )

    imported = existing = errors = relevant = 0
    messages = []
    for attachment in attachments:
        outcome = _email_import_xml_attachment(
            attachment,
            sender_email=attachment.get("sender_email"),
        )
        if not outcome["relevant"]:
            continue
        relevant += 1
        for result in outcome["results"]:
            status = result.get("status")
            if status == "IMPORTADO":
                imported += 1
            elif status == "JA_IMPORTADO":
                existing += 1
            elif not result.get("ok"):
                errors += 1
                if result.get("mensagem"):
                    messages.append(result["mensagem"])
    return {
        "attachments": relevant,
        "imported": imported,
        "existing": existing,
        "errors": errors,
        "message": "; ".join(messages[:5]),
    }


def _email_attachment_destination(folder, email_id, filename):
    base = Path(folder) / f"{email_id}_{filename}"
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix
    counter = 2
    while True:
        candidate = base.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _persist_email_locally(uid, message, existing=None, account=None, matched_filter=""):
    content = _extract_email_content(message)
    account = account or {"id": 1, "account_name": "Principal", "protocol": "pop3"}
    account_id = _email_account_id(account)
    account_label = _email_account_label(account)
    sender_name_raw, sender_email_raw = email.utils.parseaddr(message.get("From", ""))
    sender_name = _sanitize(sender_name_raw or sender_email_raw.split("@")[0])
    sender_email = _sanitize((sender_email_raw or "sem_email").lower())
    subject = _decode_text(message.get("Subject", "Sem assunto"))
    email_date = _decode_text(message.get("Date", ""))
    attachments = _email_attachment_specs(message)
    was_recovered = bool(
        existing
        and not (
            existing.get("body_text")
            or existing.get("body_html")
            or existing.get("raw_headers")
        )
    )

    conn = _conn()
    created_files = []
    attachments_added = 0
    try:
        cur = conn.cursor(dictionary=True)
        if existing:
            email_id = int(existing["id"])
            cur.execute(
                """
                UPDATE gestor_email_mensagens
                SET account_id=%s, account_label=%s, sender_name=%s,
                    sender_email=%s, subject=%s, email_date=%s,
                    filter_matched=%s, body_text=%s, body_html=%s,
                    raw_headers=%s, body_loaded_at=%s
                WHERE id=%s
                """,
                (
                    account_id,
                    account_label,
                    sender_name,
                    sender_email,
                    subject,
                    email_date,
                    str(matched_filter or "")[:255],
                    content["body_text"],
                    content["body_html"],
                    content["raw_headers"],
                    _now(),
                    email_id,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO gestor_email_mensagens
                    (account_id, account_label, uid, sender_name, sender_email,
                     subject, email_date, imported_at, filter_matched,
                     body_text, body_html, raw_headers, body_loaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    account_id,
                    account_label,
                    uid,
                    sender_name,
                    sender_email,
                    subject,
                    email_date,
                    _now(),
                    str(matched_filter or "")[:255],
                    content["body_text"],
                    content["body_html"],
                    content["raw_headers"],
                    _now(),
                ),
            )
            email_id = cur.lastrowid

        cur.execute(
            """
            SELECT id, filename, path_relativo, size_bytes
            FROM gestor_email_anexos
            WHERE email_id=%s
            ORDER BY id
            """,
            (email_id,),
        )
        local_attachments = cur.fetchall() or []
        used_attachment_ids = set()
        folder = Path(_email_attachment_dir)
        if account_id != 1:
            folder = folder / _sanitize(account_label)
        folder = folder / _sanitize(f"{sender_name} - {sender_email}")
        folder.mkdir(parents=True, exist_ok=True)

        for spec in attachments:
            matched = None
            for item in local_attachments:
                item_id = int(item.get("id") or 0)
                if item_id in used_attachment_ids:
                    continue
                if str(item.get("filename") or "") != spec["filename"]:
                    continue
                if int(item.get("size_bytes") or 0) != spec["size_bytes"]:
                    continue
                try:
                    path = _attachment_path(item.get("path_relativo"))
                except ValueError:
                    continue
                if path.is_file() and path.stat().st_size == spec["size_bytes"]:
                    matched = item
                    break
            if matched:
                used_attachment_ids.add(int(matched["id"]))
                continue

            path = _email_attachment_destination(
                folder,
                email_id,
                spec["filename"],
            )
            path.write_bytes(spec["payload"])
            created_files.append(path)
            relative = path.relative_to(Path(_email_attachment_dir)).as_posix()
            cur.execute(
                """
                INSERT INTO gestor_email_anexos
                    (email_id, filename, path_relativo, legacy_path,
                     size_bytes, created_at)
                VALUES (%s, %s, %s, NULL, %s, %s)
                """,
                (
                    email_id,
                    spec["filename"],
                    relative,
                    spec["size_bytes"],
                    _now(),
                ),
            )
            attachments_added += 1

        conn.commit()
        return {
            "email_id": email_id,
            "new": not bool(existing),
            "recovered": was_recovered,
            "attachments_added": attachments_added,
        }
    except Exception:
        conn.rollback()
        for path in created_files:
            try:
                path.unlink()
            except OSError:
                pass
        raise
    finally:
        conn.close()


def _email_local_copy_complete(email_id, message):
    local = _row(
        """
        SELECT id, raw_headers, body_loaded_at
        FROM gestor_email_mensagens
        WHERE id=%s
        """,
        (email_id,),
    )
    if not local or not local.get("raw_headers") or not local.get("body_loaded_at"):
        return False, "cabecalhos ou corpo ainda nao foram persistidos"

    expected = _email_attachment_specs(message)
    stored = _rows(
        """
        SELECT id, filename, path_relativo, size_bytes
        FROM gestor_email_anexos
        WHERE email_id=%s
        ORDER BY id
        """,
        (email_id,),
    )
    used_ids = set()
    for spec in expected:
        matched_id = 0
        for item in stored:
            item_id = int(item.get("id") or 0)
            if item_id in used_ids:
                continue
            if str(item.get("filename") or "") != spec["filename"]:
                continue
            if int(item.get("size_bytes") or 0) != spec["size_bytes"]:
                continue
            try:
                path = _attachment_path(item.get("path_relativo"))
            except ValueError:
                continue
            if path.is_file() and path.stat().st_size == spec["size_bytes"]:
                matched_id = item_id
                break
        if not matched_id:
            return False, f"anexo local ausente ou incompleto: {spec['filename']}"
        used_ids.add(matched_id)
    return True, ""


def _mark_emails_deleted_from_server(email_ids):
    ids = sorted({int(email_id) for email_id in email_ids if int(email_id) > 0})
    if not ids:
        return
    conn = _conn()
    try:
        cur = conn.cursor()
        placeholders = ", ".join(["%s"] * len(ids))
        cur.execute(
            f"""
            UPDATE gestor_email_mensagens
            SET server_deleted_at=%s
            WHERE id IN ({placeholders})
            """,
            (_now(), *ids),
        )
        conn.commit()
    finally:
        conn.close()


def _update_email_status(**values):
    with EMAIL_STATUS_LOCK:
        EMAIL_STATUS.update(values)


def _email_import_counts(local_xml=None):
    local_xml = local_xml or {
        "attachments": 0,
        "imported": 0,
        "existing": 0,
        "errors": 0,
    }
    return {
        "imported": 0,
        "recovered": 0,
        "attachments": 0,
        "xml_imported": int(local_xml.get("imported") or 0),
        "xml_existing": int(local_xml.get("existing") or 0),
        "xml_errors": int(local_xml.get("errors") or 0),
        "fetch_errors": 0,
        "deleted": 0,
        "delete_blocked": 0,
        "filtered": 0,
        "processed": 0,
    }


def _email_apply_persist_result(counts, persisted, xml_result):
    counts["attachments"] += int(persisted.get("attachments_added") or 0)
    if persisted.get("new"):
        counts["imported"] += 1
    elif persisted.get("recovered"):
        counts["recovered"] += 1
    counts["xml_imported"] += int(xml_result.get("imported") or 0)
    counts["xml_existing"] += int(xml_result.get("existing") or 0)
    counts["xml_errors"] += int(xml_result.get("errors") or 0)


def _email_status_from_counts(counts):
    _update_email_status(
        processed=counts["processed"],
        imported=counts["imported"],
        recovered=counts["recovered"],
        attachments=counts["attachments"],
        xml_imported=counts["xml_imported"],
        xml_existing=counts["xml_existing"],
        xml_errors=counts["xml_errors"],
        fetch_errors=counts["fetch_errors"],
        deleted=counts["deleted"],
    )


def _import_pop3_account(
    config,
    max_emails,
    counts,
    force_xml_attachments=False,
):
    delete_enabled = _delete_from_server_enabled()
    server = _connect_pop3(config)
    delete_pending_ids = []
    quit_confirmed = False
    try:
        count, _ = server.stat()
        max_count = int(max_emails or 0)
        start = max(1, count - max_count + 1) if max_count > 0 else 1
        _update_email_status(
            total=count - start + 1,
            processed=0,
            message=f"Importando POP3: {_email_account_label(config)}...",
        )
        for position, index in enumerate(range(start, count + 1), start=1):
            counts["processed"] = position
            uid = _email_uid_key(config, _pop_uid(server, index))
            existing = _row(
                """
                SELECT id, body_text, body_html, raw_headers, body_loaded_at
                FROM gestor_email_mensagens
                WHERE uid=%s
                """,
                (uid,),
            )
            if (
                existing
                and existing.get("raw_headers")
                and existing.get("body_loaded_at")
                and not delete_enabled
            ):
                _email_status_from_counts(counts)
                continue
            result = server.retr(index)
            if not isinstance(result, tuple):
                _email_status_from_counts(counts)
                continue
            message = email.message_from_bytes(b"\n".join(result[1]))
            matches_filter, matched = _email_message_matches_account_filter(
                message,
                config,
                force_xml_attachments=force_xml_attachments,
            )
            if not matches_filter:
                counts["filtered"] += 1
                _email_status_from_counts(counts)
                continue
            persisted = _persist_email_locally(
                uid,
                message,
                existing=existing,
                account=config,
                matched_filter=matched,
            )
            xml_result = _email_import_xml_attachments(persisted["email_id"])
            _email_apply_persist_result(counts, persisted, xml_result)
            if delete_enabled:
                complete, _ = _email_local_copy_complete(
                    persisted["email_id"],
                    message,
                )
                if complete and xml_result["ok"]:
                    server.dele(index)
                    delete_pending_ids.append(persisted["email_id"])
                    counts["deleted"] = len(delete_pending_ids)
                else:
                    counts["delete_blocked"] += 1
            _email_status_from_counts(counts)
    finally:
        try:
            server.quit()
            quit_confirmed = True
        finally:
            if quit_confirmed and delete_pending_ids:
                _mark_emails_deleted_from_server(delete_pending_ids)


def _import_imap_account(
    config,
    max_emails,
    counts,
    history_until_date=None,
    force_xml_attachments=False,
):
    server = _connect_imap(config)
    try:
        since = _imap_since_criterion(config)
        criteria = []
        if since:
            criteria.extend(["SINCE", since])
        if history_until_date:
            criteria.extend(["BEFORE", _imap_before_criterion(history_until_date)])
        mailboxes = (
            _imap_history_mailboxes(server, config)
            if history_until_date
            else [str(config.get("mailbox") or "INBOX")]
        )

        mailbox_plan = []
        for mailbox in mailboxes:
            try:
                status, data = server.select(_imap_mailbox_arg(mailbox), readonly=True)
            except Exception:
                status, data = "NO", []
            if status != "OK":
                if history_until_date and len(mailboxes) > 1:
                    _update_email_status(message=f"Ignorando pasta IMAP {mailbox}...")
                    continue
                raise RuntimeError(f"Nao foi possivel abrir a caixa IMAP {mailbox}.")
            if criteria:
                status, data = server.search(None, *criteria)
            else:
                status, data = server.search(None, "ALL")
            if status != "OK":
                if history_until_date and len(mailboxes) > 1:
                    _update_email_status(message=f"Ignorando busca IMAP {mailbox}...")
                    continue
                raise RuntimeError(f"Busca IMAP falhou na pasta {mailbox}.")
            message_ids = (data[0] or b"").split() if data else []
            if message_ids:
                mailbox_plan.append((mailbox, message_ids))

        mailbox_items = [
            (mailbox, message_id)
            for mailbox, message_ids in mailbox_plan
            for message_id in message_ids
        ]
        max_count = int(max_emails or 0)
        if max_count > 0:
            mailbox_items = mailbox_items[-max_count:]
        _update_email_status(
            total=len(mailbox_items),
            processed=0,
            message=f"Importando IMAP: {_email_account_label(config)}...",
        )
        selected_mailbox = None
        failed_mailboxes = set()
        for position, (mailbox, message_id) in enumerate(mailbox_items, start=1):
            counts["processed"] = position
            if mailbox in failed_mailboxes:
                _email_status_from_counts(counts)
                continue
            if selected_mailbox != mailbox:
                try:
                    if not server:
                        server = _connect_imap(config)
                    status, _ = server.select(_imap_mailbox_arg(mailbox), readonly=True)
                except Exception:
                    status = "NO"
                if status != "OK":
                    if history_until_date and len(mailboxes) > 1:
                        failed_mailboxes.add(mailbox)
                        _email_status_from_counts(counts)
                        continue
                    raise RuntimeError(f"Nao foi possivel abrir a caixa IMAP {mailbox}.")
                selected_mailbox = mailbox
            try:
                server, raw_uid, message, fetch_error = (
                    _imap_fetch_message_with_retry(
                        config,
                        server,
                        mailbox,
                        message_id,
                    )
                )
            except Exception as exc:
                fetch_error = exc
                raw_uid, message = None, None
            if not message:
                counts["fetch_errors"] += 1
                selected_mailbox = None
                if fetch_error:
                    _update_email_status(
                        message=(
                            f"Falha lendo IMAP {mailbox}; "
                            "a mensagem sera tentada em uma proxima execucao."
                        )
                    )
                _email_status_from_counts(counts)
                continue
            uid = _email_uid_key(config, raw_uid, mailbox=mailbox)
            existing = _row(
                """
                SELECT id, body_text, body_html, raw_headers, body_loaded_at
                FROM gestor_email_mensagens
                WHERE uid=%s
                """,
                (uid,),
            )
            if (
                existing
                and existing.get("raw_headers")
                and existing.get("body_loaded_at")
            ):
                _email_status_from_counts(counts)
                continue
            matches_filter, matched = _email_message_matches_account_filter(
                message,
                config,
                force_xml_attachments=force_xml_attachments,
            )
            if not matches_filter:
                counts["filtered"] += 1
                _email_status_from_counts(counts)
                continue
            persisted = _persist_email_locally(
                uid,
                message,
                existing=existing,
                account=config,
                matched_filter=matched,
            )
            xml_result = _email_import_xml_attachments(persisted["email_id"])
            _email_apply_persist_result(counts, persisted, xml_result)
            _email_status_from_counts(counts)
    finally:
        _imap_close_quietly(server)


def _import_emails_unlocked(
    max_emails,
    history_until_date=None,
    force_xml_attachments=False,
    account_ids=None,
):
    local_xml = _email_import_pending_local_attachments(
        max_attachments=0 if history_until_date else None,
        account_ids=account_ids if history_until_date else None,
    )
    accounts = _email_accounts(account_ids=account_ids)
    if not accounts:
        return 0, (
            "Pendencias XML locais processadas: "
            f"{local_xml['imported']} importado(s), "
            f"{local_xml['existing']} ja existente(s) e "
            f"{local_xml['errors']} erro(s). Configure uma conta POP3/IMAP "
            "para buscar novas mensagens."
        )

    counts = _email_import_counts(local_xml)
    _update_email_status(
        imported=0,
        recovered=0,
        attachments=0,
        xml_imported=counts["xml_imported"],
        xml_existing=counts["xml_existing"],
        xml_errors=counts["xml_errors"],
        fetch_errors=counts["fetch_errors"],
        deleted=0,
        message="Importando e-mails; mensagens serao mantidas no servidor...",
    )
    for config in accounts:
        protocol = _email_protocol(config)
        if protocol == "imap":
            _import_imap_account(
                config,
                max_emails,
                counts,
                history_until_date=history_until_date,
                force_xml_attachments=force_xml_attachments,
            )
        elif protocol == "pop3":
            _import_pop3_account(
                config,
                max_emails,
                counts,
                force_xml_attachments=force_xml_attachments,
            )
        else:
            counts["filtered"] += 1
            _update_email_status(
                message=(
                    f"Conta {_email_account_label(config)} ignorada: "
                    f"protocolo {protocol} nao suportado."
                )
            )

    used = _storage_used_bytes()
    limit_gb = max(float(account.get("storage_limit_gb") or 5) for account in accounts)
    limit = int(limit_gb * 1024 * 1024 * 1024)
    warning = ""
    if limit > 0 and used > limit:
        warning = " Limite configurado excedido; nenhum arquivo foi apagado."
    deletion_message = f" {_delete_policy_description()}"
    if counts["delete_blocked"]:
        deletion_message += (
            f" {counts['delete_blocked']} exclusao(oes) bloqueada(s) por copia "
            "local ou importacao XML incompleta."
        )
    xml_message = (
        f" XMLs: {counts['xml_imported']} importado(s), "
        f"{counts['xml_existing']} ja existente(s) e "
        f"{counts['xml_errors']} erro(s)."
    )
    fetch_message = (
        f" {counts['fetch_errors']} mensagem(ns) nao lida(s) por falha IMAP; "
        "execute o historico novamente apos estabilizar a conexao."
        if counts["fetch_errors"]
        else ""
    )
    if local_xml["attachments"]:
        xml_message += (
            f" Pendencias locais verificadas: "
            f"{local_xml['attachments']} anexo(s)."
        )
    filter_message = (
        f" {counts['filtered']} mensagem(ns) fora do filtro de compras/"
        "materia-prima."
        if counts["filtered"]
        else ""
    )
    return counts["imported"], (
        f"Importacao concluida: {counts['imported']} novo(s) e "
        f"{counts['recovered']} conteudo(s) recuperado(s)."
        f"{xml_message}{fetch_message}{filter_message}{deletion_message}{warning}"
    )


def _import_emails(
    max_emails,
    history_until_date=None,
    force_xml_attachments=False,
    account_ids=None,
):
    lock_conn = _conn()
    lock_cur = lock_conn.cursor(dictionary=True)
    lock_name = "riobranco_gestor_emails"
    acquired = False
    try:
        lock_cur.execute("SELECT GET_LOCK(%s, 0) AS acquired", (lock_name,))
        acquired = int((lock_cur.fetchone() or {}).get("acquired") or 0) == 1
        if not acquired:
            return 0, "Outra importacao de e-mails ja esta em andamento."
        return _import_emails_unlocked(
            max_emails,
            history_until_date=history_until_date,
            force_xml_attachments=force_xml_attachments,
            account_ids=account_ids,
        )
    finally:
        if acquired:
            try:
                lock_cur.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                lock_cur.fetchone()
            except Exception:
                pass
        lock_cur.close()
        lock_conn.close()


def _begin_email_import(message):
    with EMAIL_STATUS_LOCK:
        if EMAIL_STATUS["running"]:
            return False
        EMAIL_STATUS.update(
            running=True,
            processed=0,
            total=0,
            imported=0,
            recovered=0,
            attachments=0,
            xml_imported=0,
            xml_existing=0,
            xml_errors=0,
            fetch_errors=0,
            deleted=0,
            message=message,
        )
    return True


def _run_email_import_operation(
    max_emails,
    source="manual",
    already_started=False,
    history_until_date=None,
    force_xml_attachments=False,
    account_ids=None,
):
    if not already_started and not _begin_email_import(
        "Iniciando importacao automatica..."
        if source == "scheduler"
        else "Iniciando importacao..."
    ):
        return False
    try:
        _, message = _import_emails(
            max_emails,
            history_until_date=history_until_date,
            force_xml_attachments=force_xml_attachments,
            account_ids=account_ids,
        )
        values = {"message": message}
        if source == "scheduler":
            values["scheduler_last_run"] = _now()
        _update_email_status(**values)
    except Exception as exc:
        _update_email_status(message=f"Erro: {exc}")
    finally:
        _update_email_status(running=False)
    return True


def _email_scheduler_loop():
    try:
        config = _email_schedule_config()
    except Exception as exc:
        _update_email_status(
            scheduler_active=False,
            message=f"Agendador de e-mails desativado: {exc}",
        )
        return

    _update_email_status(scheduler_active=True)
    while True:
        try:
            now = _email_schedule_now(config)
            if _email_is_business_time(now, config):
                next_run = now + timedelta(minutes=config["interval_minutes"])
                _update_email_status(scheduler_next_run=next_run.isoformat())
                if _email_scheduler_claim(config, now):
                    _run_email_import_operation(
                        config["max_emails"],
                        source="scheduler",
                    )
                time.sleep(config["interval_minutes"] * 60)
                continue

            next_run = _email_next_business_run(now, config)
            _update_email_status(scheduler_next_run=next_run.isoformat())
            wait_seconds = max(1, int((next_run - now).total_seconds()))
            time.sleep(min(wait_seconds, 60))
        except Exception as exc:
            _update_email_status(message=f"Erro no agendador de e-mails: {exc}")
            time.sleep(60)


def _start_email_scheduler():
    global EMAIL_SCHEDULER_STARTED
    if not _email_scheduler_enabled():
        _update_email_status(scheduler_active=False, scheduler_next_run="")
        return False
    with EMAIL_SCHEDULER_LOCK:
        if EMAIL_SCHEDULER_STARTED:
            return True
        EMAIL_SCHEDULER_STARTED = True
        threading.Thread(
            target=_email_scheduler_loop,
            name="gestor-email-scheduler",
            daemon=True,
        ).start()
    return True


def _recover_existing_email_bodies():
    config = _email_config()
    if not config.get("pop_host") or not config.get("email_user") or not config.get("email_pass"):
        return 0, "Configure o POP3 primeiro."

    missing = _rows(
        """
        SELECT id, uid
        FROM gestor_email_mensagens
        WHERE COALESCE(body_text, '')='' AND COALESCE(body_html, '')=''
          AND COALESCE(account_id, 1)=1
        """
    )
    if not missing:
        return 0, "Todos os e-mails ja possuem conteudo completo."

    missing_by_uid = {str(row["uid"]): row["id"] for row in missing}
    recovered = 0
    server = _connect_pop3(config)
    try:
        count, _ = server.stat()
        _update_email_status(
            total=count,
            processed=0,
            imported=0,
            recovered=0,
            attachments=0,
            message="Recuperando conteudo dos e-mails existentes...",
        )
        for index in range(1, count + 1):
            _update_email_status(processed=index)
            uid = _pop_uid(server, index)
            email_id = missing_by_uid.get(uid)
            if not email_id:
                continue
            result = server.retr(index)
            if not isinstance(result, tuple):
                continue
            message = email.message_from_bytes(b"\n".join(result[1]))
            content = _extract_email_content(message)
            _execute(
                """
                UPDATE gestor_email_mensagens
                SET body_text=%s, body_html=%s, raw_headers=%s,
                    body_loaded_at=%s
                WHERE id=%s
                """,
                (
                    content["body_text"],
                    content["body_html"],
                    content["raw_headers"],
                    _now(),
                    email_id,
                ),
            )
            recovered += 1
            _update_email_status(recovered=recovered)
    finally:
        try:
            server.quit()
        except Exception:
            pass

    unavailable = len(missing) - recovered
    return recovered, (
        f"Recuperacao concluida: {recovered} conteudo(s) recuperado(s). "
        f"{unavailable} mensagem(ns) nao estava(m) mais disponivel(is) no POP3."
    )


@EMAIL_BP.route("/")
def index():
    accounts = _email_accounts()
    email_total = (_row("SELECT COUNT(*) total FROM gestor_email_mensagens") or {}).get("total", 0)
    attachment_total = (_row("SELECT COUNT(*) total FROM gestor_email_anexos") or {}).get("total", 0)
    used_gb = _storage_used_bytes() / 1024 / 1024 / 1024
    storage_limit = max(
        [float(account.get("storage_limit_gb") or 5) for account in accounts]
        or [5],
    )
    accounts_html = "".join(
        "<li>"
        f"{html.escape(_email_account_label(account))} "
        f"({html.escape(_email_protocol(account).upper())}) - "
        f"{html.escape(str(account.get('email_user') or ''))}"
        "</li>"
        for account in accounts
    ) or "<li>Nenhuma conta configurada.</li>"
    status_url = url_for("gestor_emails.status_importacao")
    import_url = url_for("gestor_emails.importar")
    import_history_url = url_for("gestor_emails.importar_historico_xml")
    recover_url = url_for("gestor_emails.recuperar_conteudo")
    today_text = _email_today().isoformat()
    return _email_page(f"""
    <div class="card"><h3>Resumo</h3>
      <p><b>E-mails importados:</b> {email_total}</p>
      <p><b>Anexos registrados:</b> {attachment_total}</p>
      <p><b>Uso atual:</b> {used_gb:.3f} GB de {storage_limit:g} GB</p>
      <p><b>Contas habilitadas:</b></p><ul>{accounts_html}</ul>
      <p><b>Politica de servidor:</b> {html.escape(_delete_policy_description())}</p>
      <p><b>Importacao automatica:</b> {html.escape(_email_scheduler_description())}</p>
      <form method="post" action="{import_url}">
        <label>Quantidade maxima de e-mails para verificar por conta</label>
        <input name="max_emails" type="number" min="1" value="50">
        <button>Importar agora</button>
      </form>
      <form method="post" action="{import_history_url}">
        <input name="until_date" type="hidden" value="{html.escape(today_text)}">
        <p><small>Verifica a conta BOL desde 01/01/2026 ate {html.escape(today_text)}, sem limite de quantidade, mantendo tudo no servidor.</small></p>
        <button>Importar historico XML ate hoje</button>
      </form>
      <form method="post" action="{recover_url}">
        <p><small>Busca pelo UID o corpo dos e-mails migrados do SQLite, sem duplicar anexos e sem apagar mensagens do servidor.</small></p>
        <button>Recuperar conteudo dos e-mails antigos</button>
      </form>
    </div>
    <div class="card"><h3>Status</h3><p id="email-status">Aguardando...</p>
      <p>Verificados: <span id="email-processed">0</span>/<span id="email-total">0</span></p>
      <p>Novos: <span id="email-imported">0</span> | Conteudos recuperados: <span id="email-recovered">0</span> | Anexos: <span id="email-attachments">0</span></p>
      <p>XML importados: <span id="email-xml-imported">0</span> | Ja existentes: <span id="email-xml-existing">0</span> | Erros XML: <span id="email-xml-errors">0</span> | Falhas IMAP: <span id="email-fetch-errors">0</span> | Exclusoes POP3 confirmadas: <span id="email-deleted">0</span></p>
      <p>Ultima execucao automatica: <span id="email-scheduler-last">-</span> | Proxima: <span id="email-scheduler-next">-</span></p>
    </div>
    <script>
    const timer=setInterval(async()=>{{
      const data=await fetch({json.dumps(status_url)}).then(r=>r.json());
      document.getElementById("email-status").textContent=data.message;
      document.getElementById("email-processed").textContent=data.processed;
      document.getElementById("email-total").textContent=data.total;
      document.getElementById("email-imported").textContent=data.imported;
      document.getElementById("email-recovered").textContent=data.recovered || 0;
      document.getElementById("email-attachments").textContent=data.attachments;
      document.getElementById("email-xml-imported").textContent=data.xml_imported || 0;
      document.getElementById("email-xml-existing").textContent=data.xml_existing || 0;
      document.getElementById("email-xml-errors").textContent=data.xml_errors || 0;
      document.getElementById("email-fetch-errors").textContent=data.fetch_errors || 0;
      document.getElementById("email-deleted").textContent=data.deleted || 0;
      document.getElementById("email-scheduler-last").textContent=data.scheduler_last_run || "-";
      document.getElementById("email-scheduler-next").textContent=data.scheduler_next_run || "-";
      if(!data.running && data.processed) clearInterval(timer);
    }},1000);
    </script>
    """)


def _supplier_category_options(selected):
    selected = _supplier_category(selected)
    return "".join(
        f"<option value='{html.escape(value)}' {'selected' if value == selected else ''}>"
        f"{html.escape(label)}</option>"
        for value, label in SUPPLIER_CATEGORIES.items()
    )


@EMAIL_BP.route("/fornecedores", methods=["GET", "POST"])
def fornecedores():
    if request.method == "POST":
        supplier_id = int(request.form.get("supplier_id") or 0)
        cnpj = so_num(request.form.get("cnpj") or "") or None
        name = str(request.form.get("nome") or "").strip()
        category = _supplier_category(request.form.get("categoria"))
        emails = "\n".join(_supplier_list_values(request.form.get("emails")))
        domains = "\n".join(_supplier_list_values(request.form.get("dominios")))
        notes = str(request.form.get("observacoes") or "").strip()
        active = 1 if request.form.get("ativo") else 0
        if supplier_id > 0:
            _execute(
                """
                UPDATE gestor_email_fornecedores
                SET cnpj=%s, nome=%s, categoria=%s, emails=%s, dominios=%s,
                    observacoes=%s, ativo=%s, updated_at=%s
                WHERE id=%s
                """,
                (
                    cnpj,
                    name,
                    category,
                    emails,
                    domains,
                    notes,
                    active,
                    _now(),
                    supplier_id,
                ),
            )
        else:
            _execute(
                """
                INSERT INTO gestor_email_fornecedores
                    (cnpj, nome, categoria, emails, dominios, observacoes,
                     ativo, origem, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'manual', %s, %s)
                ON DUPLICATE KEY UPDATE
                    nome=VALUES(nome),
                    categoria=VALUES(categoria),
                    emails=VALUES(emails),
                    dominios=VALUES(dominios),
                    observacoes=VALUES(observacoes),
                    ativo=VALUES(ativo),
                    updated_at=VALUES(updated_at)
                """,
                (
                    cnpj,
                    name,
                    category,
                    emails,
                    domains,
                    notes,
                    active,
                    _now(),
                    _now(),
                ),
            )
        if category == "pecas_auto":
            _refresh_supplier_import_routes()
        flash("Fornecedor salvo.")
        return redirect(url_for("gestor_emails.fornecedores"))

    rows = _rows(
        """
        SELECT
            f.*,
            COUNT(DISTINCT x.id) AS xmls,
            SUM(CASE WHEN x.status='IMPORTADO' THEN 1 ELSE 0 END) AS xmls_importados,
            SUM(CASE WHEN x.status='ERRO' THEN 1 ELSE 0 END) AS xmls_erro
        FROM gestor_email_fornecedores f
        LEFT JOIN gestor_email_xml_importacoes x ON x.fornecedor_id=f.id
        GROUP BY f.id
        ORDER BY f.categoria, f.nome
        """
    )
    cards = []
    for row in rows:
        active = "checked" if int(row.get("ativo") or 0) else ""
        cards.append(f"""
        <div class="card"><h3>{html.escape(str(row.get('nome') or 'Fornecedor'))}</h3>
          <form method="post">
            <input type="hidden" name="supplier_id" value="{int(row.get('id') or 0)}">
            <label><input type="checkbox" name="ativo" {active}> Ativo</label><br><br>
            <label>CNPJ</label>
            <input name="cnpj" value="{html.escape(str(row.get('cnpj') or ''))}">
            <label>Nome da empresa</label>
            <input name="nome" value="{html.escape(str(row.get('nome') or ''))}">
            <label>Classificacao</label>
            <select name="categoria">{_supplier_category_options(row.get('categoria'))}</select>
            <label>E-mails conhecidos</label>
            <textarea name="emails" rows="3">{html.escape(str(row.get('emails') or ''))}</textarea>
            <label>Dominios conhecidos</label>
            <textarea name="dominios" rows="2">{html.escape(str(row.get('dominios') or ''))}</textarea>
            <label>Observacoes</label>
            <textarea name="observacoes" rows="2">{html.escape(str(row.get('observacoes') or ''))}</textarea>
            <p><small>XMLs: {int(row.get('xmls') or 0)} | Importados: {int(row.get('xmls_importados') or 0)} | Erros: {int(row.get('xmls_erro') or 0)}</small></p>
            <button>Salvar fornecedor</button>
          </form>
        </div>
        """)
    new_form = f"""
    <div class="card"><h3>Novo fornecedor</h3>
      <form method="post">
        <label><input type="checkbox" name="ativo" checked> Ativo</label><br><br>
        <label>CNPJ</label><input name="cnpj">
        <label>Nome da empresa</label><input name="nome">
        <label>Classificacao</label>
        <select name="categoria">{_supplier_category_options('outros')}</select>
        <label>E-mails conhecidos</label><textarea name="emails" rows="3"></textarea>
        <label>Dominios conhecidos</label><textarea name="dominios" rows="2"></textarea>
        <label>Observacoes</label><textarea name="observacoes" rows="2"></textarea>
        <button>Cadastrar fornecedor</button>
      </form>
    </div>
    """
    return _email_page(
        new_form
        + "".join(cards)
        + """
        <div class="card">
          <p><b>Uso da classificacao:</b> materia-prima, distribuidora e outros seguem para o Importar XML/estoque conforme a NF-e. Pecas auto direciona a NF-e para pre-lancamento de manutencao da frota.</p>
          <p><small>Quando um XML novo chegar por e-mail e o CNPJ ainda nao existir, o fornecedor sera criado automaticamente como Outros com CNPJ, nome, e-mail e dominio do remetente.</small></p>
        </div>
        """
    )


@EMAIL_BP.route("/config", methods=["GET", "POST"])
def config():
    if request.method == "POST":
        account_id = int(request.form.get("account_id", 1))
        current = _row(
            "SELECT * FROM gestor_email_config WHERE id=%s",
            (account_id,),
        ) or {}
        password = request.form.get("email_pass", "") or current.get("email_pass", "")
        _execute(
            """
            INSERT INTO gestor_email_config (
                id, account_name, protocol, enabled, pop_host, pop_port,
                use_ssl, mailbox, email_user, email_pass, smtp_host, smtp_port,
                smtp_use_tls, since_date, filter_keywords, storage_limit_gb,
                delete_from_server
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
            ON DUPLICATE KEY UPDATE
                account_name=VALUES(account_name),
                protocol=VALUES(protocol),
                enabled=VALUES(enabled),
                pop_host=VALUES(pop_host),
                pop_port=VALUES(pop_port),
                use_ssl=VALUES(use_ssl),
                mailbox=VALUES(mailbox),
                email_user=VALUES(email_user),
                email_pass=VALUES(email_pass),
                smtp_host=VALUES(smtp_host),
                smtp_port=VALUES(smtp_port),
                smtp_use_tls=VALUES(smtp_use_tls),
                since_date=VALUES(since_date),
                filter_keywords=VALUES(filter_keywords),
                storage_limit_gb=VALUES(storage_limit_gb),
                delete_from_server=0
            """,
            (
                account_id,
                request.form.get("account_name", ""),
                request.form.get("protocol", "pop3"),
                1 if request.form.get("enabled") else 0,
                request.form.get("pop_host", ""),
                int(request.form.get("pop_port", 995)),
                1 if request.form.get("use_ssl") else 0,
                request.form.get("mailbox", "INBOX"),
                request.form.get("email_user", ""),
                password,
                request.form.get("smtp_host", ""),
                int(request.form.get("smtp_port", 587)),
                1 if request.form.get("smtp_use_tls") else 0,
                request.form.get("since_date", ""),
                request.form.get("filter_keywords", ""),
                float(request.form.get("storage_limit_gb", 5)),
            ),
        )
        flash("Configuracao salva.")
        return redirect(url_for("gestor_emails.config"))

    rows = _rows("SELECT * FROM gestor_email_config ORDER BY id")
    forms = []
    for data in rows:
        protocol = _email_protocol(data)
        checked_enabled = "checked" if _email_account_enabled(data) else ""
        checked_ssl = "checked" if data.get("use_ssl") else ""
        checked_tls = "checked" if data.get("smtp_use_tls") else ""
        selected_pop3 = "selected" if protocol == "pop3" else ""
        selected_imap = "selected" if protocol == "imap" else ""
        forms.append(f"""
        <div class="card"><h3>{html.escape(_email_account_label(data))}</h3>
        <form method="post">
          <input type="hidden" name="account_id" value="{int(data.get('id') or 1)}">
          <label><input type="checkbox" name="enabled" {checked_enabled}> Conta habilitada</label><br><br>
          <label>Nome da conta</label>
          <input name="account_name" value="{html.escape(str(data.get('account_name') or ''))}">
          <label>Protocolo de entrada</label>
          <select name="protocol">
            <option value="pop3" {selected_pop3}>POP3</option>
            <option value="imap" {selected_imap}>IMAP</option>
          </select>
          <label>Servidor de entrada</label>
          <input name="pop_host" value="{html.escape(str(data.get('pop_host') or ''))}">
          <label>Porta de entrada</label>
          <input name="pop_port" type="number" value="{data.get('pop_port') or 995}">
          <label><input type="checkbox" name="use_ssl" {checked_ssl}> Usar SSL na entrada</label><br><br>
          <label>Mailbox IMAP</label>
          <input name="mailbox" value="{html.escape(str(data.get('mailbox') or 'INBOX'))}">
          <label>E-mail</label>
          <input name="email_user" value="{html.escape(str(data.get('email_user') or ''))}">
          <label>Senha / senha de app</label>
          <input name="email_pass" type="password" placeholder="Deixe vazio para manter a senha atual">
          <label>Servidor SMTP</label>
          <input name="smtp_host" value="{html.escape(str(data.get('smtp_host') or ''))}">
          <label>Porta SMTP</label>
          <input name="smtp_port" type="number" value="{data.get('smtp_port') or 587}">
          <label><input type="checkbox" name="smtp_use_tls" {checked_tls}> Usar TLS no SMTP</label><br><br>
          <label>Buscar mensagens a partir de</label>
          <input name="since_date" placeholder="2026-01-01" value="{html.escape(str(data.get('since_date') or ''))}">
          <label>Filtro de compras / materia-prima</label>
          <textarea name="filter_keywords" rows="4">{html.escape(str(data.get('filter_keywords') or ''))}</textarea>
          <label>Limite de armazenamento em GB</label>
          <input name="storage_limit_gb" type="number" step="0.1" value="{data.get('storage_limit_gb') or 5}">
          <p><b>Politica de exclusao:</b> mensagens permanecem no servidor; IMAP nao executa exclusao.</p>
          <button>Salvar configuracao</button>
        </form></div>
        """)
    if not any(int(row.get("id") or 0) == 2 for row in rows):
        forms.append(f"""
        <div class="card"><h3>Nova conta</h3>
          <form method="post">
            <input type="hidden" name="account_id" value="2">
            <label><input type="checkbox" name="enabled" checked> Conta habilitada</label><br><br>
            <label>Nome da conta</label>
            <input name="account_name" value="BOL Compras Materia Prima">
            <label>Protocolo de entrada</label>
            <select name="protocol">
              <option value="imap" selected>IMAP</option>
              <option value="pop3">POP3</option>
            </select>
            <label>Servidor de entrada</label>
            <input name="pop_host" value="imap.bol.com.br">
            <label>Porta de entrada</label>
            <input name="pop_port" type="number" value="993">
            <label><input type="checkbox" name="use_ssl" checked> Usar SSL na entrada</label><br><br>
            <label>Mailbox IMAP</label>
            <input name="mailbox" value="INBOX">
            <label>E-mail</label>
            <input name="email_user" value="">
            <label>Senha / senha de app</label>
            <input name="email_pass" type="password">
            <label>Servidor SMTP</label>
            <input name="smtp_host" value="smtp.bol.com.br">
            <label>Porta SMTP</label>
            <input name="smtp_port" type="number" value="587">
            <label><input type="checkbox" name="smtp_use_tls" checked> Usar TLS no SMTP</label><br><br>
            <label>Buscar mensagens a partir de</label>
            <input name="since_date" value="2026-01-01">
            <label>Filtro de compras / materia-prima</label>
            <textarea name="filter_keywords" rows="4">compra,compras,materia prima,matéria prima,insumo,fornecedor,nfe,nf-e,xml,pecas,peças,manutencao,manutenção,frota</textarea>
            <label>Limite de armazenamento em GB</label>
            <input name="storage_limit_gb" type="number" step="0.1" value="5">
            <p><b>Politica de exclusao:</b> mensagens permanecem no servidor; IMAP nao executa exclusao.</p>
            <button>Criar conta</button>
          </form>
        </div>
        """)
    return _email_page(f"""
    {''.join(forms)}
    <div class="card">
      <p><b>Politica de exclusao:</b> {html.escape(_delete_policy_description())}</p>
      <p><b>Agendador:</b> {html.escape(_email_scheduler_description())}</p>
      <p><small>As credenciais vindas do .env podem sobrescrever a conta BOL no proximo restart.</small></p>
    </div>
    """)


@EMAIL_BP.route("/importar", methods=["POST"])
def importar():
    max_emails = max(1, int(request.form.get("max_emails", 50)))
    if not _begin_email_import("Iniciando importacao..."):
        flash("Ja existe uma importacao em andamento.")
        return redirect(url_for("gestor_emails.index"))
    threading.Thread(
        target=_run_email_import_operation,
        args=(max_emails, "manual", True),
        daemon=True,
    ).start()
    return redirect(url_for("gestor_emails.index"))


@EMAIL_BP.route("/importar-historico-xml", methods=["POST"])
def importar_historico_xml():
    until_date = request.form.get("until_date") or _email_today().isoformat()
    parsed = _parse_email_date(until_date) or _email_today()
    bol_account_id = int(os.environ.get("RB_EMAIL_BOL_ACCOUNT_ID", "2"))
    if not _begin_email_import(
        f"Iniciando historico XML BOL ate {parsed.isoformat()}..."
    ):
        flash("Ja existe uma importacao em andamento.")
        return redirect(url_for("gestor_emails.index"))
    threading.Thread(
        target=_run_email_import_operation,
        kwargs={
            "max_emails": 0,
            "source": "historico_xml",
            "already_started": True,
            "history_until_date": parsed.isoformat(),
            "force_xml_attachments": True,
            "account_ids": [bol_account_id],
        },
        daemon=True,
    ).start()
    return redirect(url_for("gestor_emails.index"))


@EMAIL_BP.route("/recuperar-conteudo", methods=["POST"])
def recuperar_conteudo():
    with EMAIL_STATUS_LOCK:
        if EMAIL_STATUS["running"]:
            flash("Ja existe uma operacao de e-mail em andamento.")
            return redirect(url_for("gestor_emails.index"))
        EMAIL_STATUS.update(
            running=True,
            processed=0,
            total=0,
            imported=0,
            recovered=0,
            attachments=0,
            xml_imported=0,
            xml_existing=0,
            xml_errors=0,
            fetch_errors=0,
            deleted=0,
            message="Iniciando recuperacao...",
        )

    def task():
        try:
            _, message = _recover_existing_email_bodies()
            _update_email_status(message=message)
        except Exception as exc:
            _update_email_status(message=f"Erro: {exc}")
        finally:
            _update_email_status(running=False)

    threading.Thread(target=task, daemon=True).start()
    return redirect(url_for("gestor_emails.index"))


@EMAIL_BP.route("/status-importacao")
def status_importacao():
    with EMAIL_STATUS_LOCK:
        data = dict(EMAIL_STATUS)
    total = data.get("total") or 0
    processed = data.get("processed") or 0
    data["percent"] = int((processed / total) * 100) if total else 0
    return jsonify(data)


@EMAIL_BP.route("/emails")
def emails_page():
    rows = _rows(
        """
        SELECT e.*, COUNT(a.id) total_anexos
        FROM gestor_email_mensagens e
        LEFT JOIN gestor_email_anexos a ON a.email_id=e.id
        GROUP BY e.id
        ORDER BY e.id DESC
        LIMIT 1000
        """
    )
    table = "".join(
        f"<tr class='email-row' onclick='abrirEmail({int(row['id'])})' title='Clique para abrir o e-mail completo'><td>{row['id']}</td>"
        f"<td>{html.escape(str(row.get('account_label') or 'Principal'))}</td>"
        f"<td>{html.escape(str(row.get('sender_name') or ''))}<br><small>{html.escape(str(row.get('sender_email') or ''))}</small></td>"
        f"<td>{html.escape(str(row.get('subject') or ''))}<small class='email-preview'>{html.escape(_email_preview(row) or 'Conteudo completo ainda nao recuperado.')}</small></td>"
        f"<td>{html.escape(str(row.get('email_date') or ''))}</td>"
        f"<td>{row.get('total_anexos') or 0}</td></tr>"
        for row in rows
    )
    detail_base = url_for("gestor_emails.email_detail", email_id=0).rsplit("0", 1)[0]
    return _email_page(
        "<div class='card'><h3>E-mails importados</h3><p><small>Clique em uma linha para visualizar os dados e o conteudo completo.</small></p><div class='scroll'><table>"
        "<tr><th>ID</th><th>Conta</th><th>Fornecedor/remetente</th><th>Assunto</th><th>Data</th><th>Anexos</th></tr>"
        f"{table}</table></div></div>"
        """
        <div id="emailModal" class="email-modal" role="dialog" aria-modal="true" aria-labelledby="emailModalTitulo">
          <div class="email-modal-card">
            <div class="email-modal-head">
              <div><h3 id="emailModalTitulo">Carregando e-mail...</h3><small id="emailModalSubtitulo"></small></div>
              <button class="email-modal-close" type="button" onclick="fecharEmail()" aria-label="Fechar">&times;</button>
            </div>
            <div class="email-modal-body">
              <div id="emailMeta" class="email-meta"></div>
              <div id="emailAnexos" class="email-anexos"></div>
              <div id="emailConteudo" class="email-content"><div class="email-empty">Carregando...</div></div>
              <details style="margin-top:16px"><summary>Cabecalhos completos</summary><pre id="emailHeaders" class="email-headers"></pre></details>
            </div>
          </div>
        </div>
        """
        f"""
        <script>
        const EMAIL_DETAIL_BASE={json.dumps(detail_base)};
        const modalEmail=document.getElementById("emailModal");
        const textoSeguro=(valor)=>String(valor ?? "");
        const adicionarMeta=(rotulo,valor)=>{{
          const meta=document.getElementById("emailMeta");
          const nome=document.createElement("b");
          const conteudo=document.createElement("span");
          nome.textContent=rotulo;
          conteudo.textContent=textoSeguro(valor) || "-";
          meta.append(nome,conteudo);
        }};
        async function abrirEmail(id){{
          modalEmail.classList.add("open");
          document.body.style.overflow="hidden";
          document.getElementById("emailModalTitulo").textContent="Carregando e-mail...";
          document.getElementById("emailModalSubtitulo").textContent="";
          document.getElementById("emailMeta").replaceChildren();
          document.getElementById("emailAnexos").replaceChildren();
          document.getElementById("emailConteudo").innerHTML="<div class='email-empty'>Carregando...</div>";
          document.getElementById("emailHeaders").textContent="";
          try {{
            const resposta=await fetch(EMAIL_DETAIL_BASE+id);
            if(!resposta.ok) throw new Error("E-mail nao encontrado.");
            const data=await resposta.json();
            document.getElementById("emailModalTitulo").textContent=data.subject || "Sem assunto";
            document.getElementById("emailModalSubtitulo").textContent=`Mensagem #${{data.id}}`;
            adicionarMeta("Remetente", [data.sender_name,data.sender_email].filter(Boolean).join(" - "));
            adicionarMeta("Conta", data.account_label);
            adicionarMeta("Filtro", data.filter_matched);
            adicionarMeta("Data do e-mail", data.email_date);
            adicionarMeta("Importado em", data.imported_at);
            adicionarMeta("Conteudo carregado em", data.body_loaded_at);
            document.getElementById("emailHeaders").textContent=data.raw_headers || "Cabecalhos nao disponiveis no SQLite antigo.";

            const anexos=document.getElementById("emailAnexos");
            if(data.attachments.length){{
              const titulo=document.createElement("b");
              titulo.textContent="Anexos:";
              anexos.appendChild(titulo);
              data.attachments.forEach((anexo)=>{{
                const link=document.createElement("a");
                link.href=anexo.url;
                link.textContent=`${{anexo.filename}} (${{anexo.size_mb}} MB)`;
                link.addEventListener("click",(evento)=>evento.stopPropagation());
                anexos.appendChild(link);
              }});
            }}

            const conteudo=document.getElementById("emailConteudo");
            conteudo.replaceChildren();
            if(data.body_html){{
              const frame=document.createElement("iframe");
              frame.setAttribute("sandbox","");
              frame.title="Conteudo HTML do e-mail";
              const politica="<meta http-equiv=\\"Content-Security-Policy\\" content=\\"default-src 'none'; img-src data:; style-src 'unsafe-inline'\\">";
              frame.srcdoc=politica+data.body_html;
              conteudo.appendChild(frame);
            }} else if(data.body_text){{
              const pre=document.createElement("pre");
              pre.textContent=data.body_text;
              conteudo.appendChild(pre);
            }} else {{
              const aviso=document.createElement("div");
              aviso.className="email-empty";
              aviso.textContent=data.body_message;
              conteudo.appendChild(aviso);
            }}
          }} catch(erro) {{
            document.getElementById("emailConteudo").innerHTML="<div class='email-empty'>"+textoSeguro(erro.message)+"</div>";
          }}
        }}
        function fecharEmail(){{
          modalEmail.classList.remove("open");
          document.body.style.overflow="";
        }}
        modalEmail.addEventListener("click",(evento)=>{{if(evento.target===modalEmail) fecharEmail();}});
        document.addEventListener("keydown",(evento)=>{{if(evento.key==="Escape") fecharEmail();}});
        </script>
        """
    )


@EMAIL_BP.route("/email/<int:email_id>")
def email_detail(email_id):
    data = _row(
        "SELECT * FROM gestor_email_mensagens WHERE id=%s",
        (email_id,),
    )
    if not data:
        return jsonify({"error": "E-mail nao encontrado."}), 404
    attachments = _rows(
        """
        SELECT id, filename, size_bytes
        FROM gestor_email_anexos
        WHERE email_id=%s
        ORDER BY id
        """,
        (email_id,),
    )
    return jsonify(
        {
            "id": data["id"],
            "account_label": data.get("account_label") or "Principal",
            "filter_matched": data.get("filter_matched") or "",
            "sender_name": data.get("sender_name") or "",
            "sender_email": data.get("sender_email") or "",
            "subject": data.get("subject") or "",
            "email_date": data.get("email_date") or "",
            "imported_at": data.get("imported_at") or "",
            "body_loaded_at": data.get("body_loaded_at") or "",
            "body_text": data.get("body_text") or "",
            "body_html": data.get("body_html") or "",
            "raw_headers": data.get("raw_headers") or "",
            "body_message": (
                "O SQLite antigo nao armazenava o corpo deste e-mail e a "
                "mensagem ainda nao foi recuperada do servidor POP3. Os "
                "metadados e anexos permanecem preservados."
            ),
            "attachments": [
                {
                    "filename": item.get("filename") or "anexo",
                    "size_mb": f"{(item.get('size_bytes') or 0) / 1024 / 1024:.2f}",
                    "url": url_for(
                        "gestor_emails.download",
                        attachment_id=item["id"],
                    ),
                }
                for item in attachments
            ],
        }
    )


@EMAIL_BP.route("/anexos")
def anexos_page():
    rows = _rows(
        """
        SELECT a.*, e.sender_name, e.sender_email, e.subject
        FROM gestor_email_anexos a
        JOIN gestor_email_mensagens e ON e.id=a.email_id
        ORDER BY a.id DESC
        LIMIT 2000
        """
    )
    table = "".join(
        f"<tr><td>{html.escape(str(row.get('account_label') or 'Principal'))}</td>"
        f"<td>{html.escape(str(row.get('sender_name') or ''))}<br><small>{html.escape(str(row.get('sender_email') or ''))}</small></td>"
        f"<td>{html.escape(str(row.get('filename') or ''))}<br><small>{html.escape(str(row.get('subject') or ''))}</small></td>"
        f"<td>{(row.get('size_bytes') or 0)/1024/1024:.2f} MB</td>"
        f"<td><a href='{url_for('gestor_emails.download', attachment_id=row['id'])}'>Baixar</a></td></tr>"
        for row in rows
    )
    return _email_page(
        "<div class='card'><h3>Anexos organizados</h3><div class='scroll'><table>"
        "<tr><th>Conta</th><th>Fornecedor/remetente</th><th>Arquivo</th><th>Tamanho</th><th>Abrir</th></tr>"
        f"{table}</table></div></div>"
    )


@EMAIL_BP.route("/download/<int:attachment_id>")
def download(attachment_id):
    data = _row("SELECT * FROM gestor_email_anexos WHERE id=%s", (attachment_id,))
    if not data:
        return "Arquivo nao encontrado", 404
    try:
        path = _attachment_path(data.get("path_relativo"))
    except ValueError:
        return "Caminho de arquivo invalido", 400
    if not path.is_file():
        return "Arquivo nao encontrado", 404
    return send_file(path, as_attachment=True, download_name=data.get("filename") or path.name)


def register_legacy_services(
    app,
    conn_factory,
    data_root,
    legacy_xml_root=None,
    legacy_email_root=None,
    migrate=False,
    abastecimento_import_callback=None,
):
    global _conn_factory
    global _xml_upload_dir
    global _email_attachment_dir
    global _legacy_xml_root
    global _legacy_email_root
    global _abastecimento_import_callback

    _conn_factory = conn_factory
    _xml_upload_dir = Path(
        os.environ.get(
            "RB_IMPORTAR_XML_DATA_DIR",
            str(Path(data_root) / "ImportarXml" / "uploads"),
        )
    )
    _email_attachment_dir = Path(
        os.environ.get(
            "RB_GESTOR_EMAIL_DATA_DIR",
            str(Path(data_root) / "GestorEmails" / "anexos"),
        )
    )
    _legacy_xml_root = Path(
        legacy_xml_root
        or os.environ.get("RB_IMPORTAR_XML_LEGACY_DIR", "ImportarXml")
    )
    _legacy_email_root = Path(
        legacy_email_root
        or os.environ.get("RB_GESTOR_EMAIL_LEGACY_DIR", "GestorEmails")
    )
    _abastecimento_import_callback = abastecimento_import_callback

    ensure_service_schema()
    migration_details = migrate_legacy_service_data() if migrate else {}
    app.register_blueprint(XML_BP)
    app.register_blueprint(EMAIL_BP)
    _start_email_scheduler()
    return migration_details
