import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_NAME = Path(
    os.getenv("DATABASE_PATH", BASE_DIR / "homologacao.db")
)
SCHEMA_PATH = BASE_DIR / "schema.sql"


def get_connection():
    DB_NAME.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    conn = get_connection()

    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        conn.executescript(f.read())

    colunas_motores = {
        coluna["name"]
        for coluna in conn.execute(
            "PRAGMA table_info(motores)"
        ).fetchall()
    }

    if "ultimo_contato" not in colunas_motores:
        conn.execute("""
            ALTER TABLE motores
            ADD COLUMN ultimo_contato DATETIME
        """)

    conn.commit()

    qtd = conn.execute(
        "SELECT COUNT(*) total FROM setores"
    ).fetchone()["total"]

    if qtd == 0:

        conn.execute("""
            INSERT INTO setores(nome,descricao)
            VALUES
            ('Envase','Linha de Envase'),
            ('Rotulagem','Linha de Rotulagem'),
            ('Utilidades','Compressores e Chillers')
        """)

        conn.commit()

    conn.close()
