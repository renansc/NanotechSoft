from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from .config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings

    def connection_kwargs(self, database_name: str) -> dict[str, object]:
        if self.settings.database_url:
            kwargs = conninfo_to_dict(self.settings.database_url)
            kwargs["dbname"] = database_name
        else:
            kwargs = {
                "host": self.settings.pg_host,
                "port": self.settings.pg_port,
                "user": self.settings.pg_user,
                "password": self.settings.pg_password,
                "dbname": database_name,
            }
        sslmode = str(kwargs.get("sslmode") or "").strip()
        if self.settings.pg_sslmode:
            sslmode = self.settings.pg_sslmode
        kwargs["sslmode"] = sslmode or "prefer"
        kwargs["row_factory"] = dict_row
        return kwargs

    def _connect(self, database_name: str) -> psycopg.Connection:
        return psycopg.connect(**self.connection_kwargs(database_name))

    @contextmanager
    def clinic(self) -> Iterator[psycopg.Connection]:
        conn = self._connect(self.settings.pg_database)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def router(self) -> Iterator[psycopg.Connection]:
        conn = self._connect(self.settings.pacs_router_database)
        try:
            yield conn
        finally:
            conn.close()

    def ping(self) -> dict[str, object]:
        with self.clinic() as conn:
            with conn.cursor() as cur:
                cur.execute("select current_database() as db, current_user as username, version() as version")
                info = cur.fetchone() or {}
                cur.execute("select count(*) as total from information_schema.tables where table_schema = 'public'")
                public_total = cur.fetchone() or {}
        return {
            "ok": True,
            "database": info.get("db"),
            "user": info.get("username"),
            "version": info.get("version"),
            "public_tables": public_total.get("total", 0),
        }
