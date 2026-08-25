#!/usr/bin/env python3
"""Replica snapshots autorizados do banco local para um cache MySQL remoto.

Esta ferramenta nunca e chamada por up.sh, update.sh ou pelo startup da
aplicacao. O sentido permitido e sempre origem local -> cache remoto.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
import re
import sys

import mysql.connector


IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")
SENSITIVE_TABLES = {
    "usuarios",
    "gestor_email_contas",
    "nfe_config",
    "portal_config_secrets",
}


def load_env_file(path: Path) -> None:
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


def load_runtime_env() -> None:
    root = Path(__file__).resolve().parents[1]
    configured = str(os.environ.get("NANOTECH_ENV_FILE") or "").strip()
    if configured:
        path = Path(configured)
        load_env_file(path if path.is_absolute() else root / path)
        return
    for filename in (".env", ".env_local"):
        path = root / filename
        if path.exists():
            load_env_file(path)
            return


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


def identifier(value: str) -> str:
    value = str(value or "").strip()
    if not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"identificador MySQL invalido: {value!r}")
    return value


def quoted(value: str) -> str:
    return f"`{identifier(value)}`"


def parse_tables(raw: str) -> list[str]:
    tables = []
    seen = set()
    for item in str(raw or "").split(","):
        table = identifier(item) if item.strip() else ""
        if table and table not in seen:
            seen.add(table)
            tables.append(table)
    if not tables:
        raise ValueError("CACHE_SYNC_TABLES deve listar explicitamente as tabelas autorizadas")
    if "cloud_cache_status" in seen:
        raise ValueError("cloud_cache_status e metadado do cache e nao pode ser espelhado")
    return tables


def database_config(prefix: str) -> dict:
    values = {
        "host": os.environ.get(f"{prefix}_HOST", "").strip(),
        "port": int(os.environ.get(f"{prefix}_PORT", "3306")),
        "user": os.environ.get(f"{prefix}_USER", "").strip(),
        "password": os.environ.get(f"{prefix}_PASSWORD", ""),
        "database": os.environ.get(f"{prefix}_NAME", "").strip(),
        "charset": "utf8mb4",
        "collation": "utf8mb4_unicode_ci",
        "connection_timeout": int(os.environ.get("CACHE_SYNC_CONNECT_TIMEOUT", "15")),
    }
    missing = [key for key in ("host", "user", "password", "database") if not values[key]]
    if missing:
        raise ValueError(f"configuracao {prefix} incompleta: {', '.join(missing)}")
    identifier(values["database"])
    return values


def table_columns(conn, table: str) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s
        ORDER BY ORDINAL_POSITION
        """,
        (table,),
    )
    columns = [row[0] for row in cur.fetchall()]
    cur.close()
    return columns


def ensure_compatible_table(source, target, table: str) -> list[str]:
    source_columns = table_columns(source, table)
    target_columns = table_columns(target, table)
    if not source_columns:
        raise ValueError(f"tabela de origem nao encontrada: {table}")
    if not target_columns:
        raise ValueError(f"tabela de cache nao preparada: {table}")
    if source_columns != target_columns:
        raise ValueError(f"schema divergente na tabela {table}; prepare o cache antes de sincronizar")
    return source_columns


def ensure_status_table(target) -> None:
    cur = target.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cloud_cache_status (
            client_id VARCHAR(80) NOT NULL,
            dataset VARCHAR(120) NOT NULL,
            row_count BIGINT NOT NULL DEFAULT 0,
            source_snapshot_at DATETIME(6) NOT NULL,
            synced_at DATETIME(6) NOT NULL,
            PRIMARY KEY (client_id, dataset)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    target.commit()
    cur.close()


def validate_safety(source_config: dict, target_config: dict, tables: list[str]) -> None:
    same_endpoint = (
        source_config["host"].lower(),
        int(source_config["port"]),
        source_config["database"].lower(),
    ) == (
        target_config["host"].lower(),
        int(target_config["port"]),
        target_config["database"].lower(),
    )
    if same_endpoint:
        raise ValueError("origem e destino apontam para o mesmo banco; sincronizacao bloqueada")
    if not target_config["database"].lower().startswith("cache_") and not env_flag("CACHE_SYNC_ALLOW_ANY_TARGET"):
        raise ValueError("o banco de destino deve comecar com cache_ (ou use CACHE_SYNC_ALLOW_ANY_TARGET=1 conscientemente)")
    sensitive = sorted(set(tables) & SENSITIVE_TABLES)
    if sensitive and not env_flag("CACHE_SYNC_ALLOW_SENSITIVE"):
        raise ValueError(
            "tabelas sensiveis exigem CACHE_SYNC_ALLOW_SENSITIVE=1: " + ", ".join(sensitive)
        )


def count_rows(conn, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {quoted(table)}")
    count = int((cur.fetchone() or [0])[0])
    cur.close()
    return count


def replace_table_snapshot(source, target, table: str, columns: list[str], batch_size: int) -> int:
    source_cur = source.cursor()
    target_cur = target.cursor()
    column_sql = ", ".join(quoted(column) for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    target_cur.execute(f"DELETE FROM {quoted(table)}")
    source_cur.execute(f"SELECT {column_sql} FROM {quoted(table)}")
    inserted = 0
    while True:
        rows = source_cur.fetchmany(batch_size)
        if not rows:
            break
        target_cur.executemany(
            f"INSERT INTO {quoted(table)} ({column_sql}) VALUES ({placeholders})",
            rows,
        )
        inserted += len(rows)
    source_cur.close()
    target_cur.close()
    return inserted


def sync_cache(*, dry_run: bool, batch_size: int) -> dict:
    tables = parse_tables(os.environ.get("CACHE_SYNC_TABLES", ""))
    source_config = database_config("CACHE_SOURCE_DB")
    target_config = database_config("CACHE_TARGET_DB")
    validate_safety(source_config, target_config, tables)

    client_id = identifier(os.environ.get("CACHE_SYNC_CLIENT_ID", "").replace("-", "_"))
    dataset = str(os.environ.get("CACHE_SYNC_DATASET") or source_config["database"]).strip()
    if not dataset or len(dataset) > 120:
        raise ValueError("CACHE_SYNC_DATASET invalido")

    source = mysql.connector.connect(**source_config)
    target = mysql.connector.connect(**target_config)
    try:
        table_plan = []
        for table in tables:
            columns = ensure_compatible_table(source, target, table)
            table_plan.append((table, columns, count_rows(source, table)))
        if dry_run:
            return {
                "client": client_id,
                "dataset": dataset,
                "dryRun": True,
                "tables": {table: count for table, _, count in table_plan},
            }

        ensure_status_table(target)
        source.start_transaction(consistent_snapshot=True)
        target.start_transaction()
        target_cur = target.cursor()
        target_cur.execute("SET FOREIGN_KEY_CHECKS=0")
        inserted = {}
        try:
            for table, columns, _ in table_plan:
                inserted[table] = replace_table_snapshot(source, target, table, columns, batch_size)
            snapshot_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
            target_cur.execute("SET FOREIGN_KEY_CHECKS=1")
            target_cur.execute(
                """
                INSERT INTO cloud_cache_status
                    (client_id, dataset, row_count, source_snapshot_at, synced_at)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    row_count=VALUES(row_count),
                    source_snapshot_at=VALUES(source_snapshot_at),
                    synced_at=VALUES(synced_at)
                """,
                (client_id, dataset, sum(inserted.values()), snapshot_at, snapshot_at),
            )
            target.commit()
            source.rollback()
        except Exception:
            target.rollback()
            source.rollback()
            raise
        finally:
            target_cur.close()
        return {
            "client": client_id,
            "dataset": dataset,
            "dryRun": False,
            "tables": inserted,
        }
    finally:
        source.close()
        target.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Atualiza o cache remoto a partir do banco local")
    parser.add_argument("--dry-run", action="store_true", help="valida conexoes, schemas e contagens sem gravar")
    parser.add_argument("--yes", action="store_true", help="confirma a substituicao atomica das tabelas do cache")
    parser.add_argument("--batch-size", type=int, default=500, help="linhas por lote (padrao: 500)")
    return parser


def main(argv=None) -> int:
    load_runtime_env()
    args = build_parser().parse_args(argv)
    try:
        if not args.dry_run:
            if not env_flag("CACHE_SYNC_ENABLED"):
                raise ValueError("defina CACHE_SYNC_ENABLED=1 somente no cliente autorizado")
            if not args.yes:
                raise ValueError("use --yes para confirmar a escrita exclusiva no banco de cache")
        if args.batch_size < 1 or args.batch_size > 5000:
            raise ValueError("--batch-size deve ficar entre 1 e 5000")
        result = sync_cache(dry_run=args.dry_run, batch_size=args.batch_size)
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    mode = "simulacao" if result["dryRun"] else "sincronizacao"
    print(f"{mode} concluida: cliente={result['client']} dataset={result['dataset']}")
    for table, count in result["tables"].items():
        print(f"- {table}: {count} linha(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
