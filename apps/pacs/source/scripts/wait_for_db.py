import time
from pathlib import Path

import psycopg

from raiox_pacs.config import Settings
from raiox_pacs.db import Database


def wait_database(name: str, settings: Settings, timeout_seconds: int = 90) -> None:
    started = time.time()
    database = Database(settings)
    while True:
        try:
            with psycopg.connect(**database.connection_kwargs(name)) as conn:
                with conn.cursor() as cur:
                    cur.execute("select 1")
                    cur.fetchone()
            print(f"Database {name} is ready.")
            return
        except Exception as exc:
            if time.time() - started >= timeout_seconds:
                raise RuntimeError(f"Timeout waiting for database {name}: {exc}") from exc
            time.sleep(2)


def main() -> None:
    settings = Settings.load(Path(__file__).resolve().parent.parent)
    wait_database(settings.pg_database, settings)
    if (settings.pacs_router_database or "").strip():
        wait_database(settings.pacs_router_database, settings)


if __name__ == "__main__":
    main()
