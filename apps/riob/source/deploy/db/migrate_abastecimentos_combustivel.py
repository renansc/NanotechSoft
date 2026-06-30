#!/usr/bin/env python3
import argparse
import os

import mysql.connector


VEICULOS_DIESEL_S10 = ("60", "61", "30", "31", "58", "57", "59")
COMBUSTIVEIS_VEICULO_VALIDOS = (
    "diesel_s10",
    "diesel_500",
    "gasolina",
    "etanol",
    "flex",
)


def db_config():
    return {
        "host": os.environ.get("DB_HOST", "db"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "riobranco"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "riobranco"),
    }


def placeholders(values):
    return ", ".join(["%s"] * len(values))


def fetch_rows(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchall() or []


def print_summary(cur, title):
    print(f"\n{title}")
    veiculos = fetch_rows(
        cur,
        """
        SELECT combustivel_padrao, COUNT(*) AS quantidade
        FROM veiculos
        GROUP BY combustivel_padrao
        ORDER BY combustivel_padrao
        """,
    )
    for row in veiculos:
        print(f"  veiculos {row['combustivel_padrao']}: {row['quantidade']}")

    abastecimentos = fetch_rows(
        cur,
        """
        SELECT combustivel_tipo, COUNT(*) AS quantidade
        FROM abastecimentos
        GROUP BY combustivel_tipo
        ORDER BY combustivel_tipo
        """,
    )
    for row in abastecimentos:
        print(f"  abastecimentos {row['combustivel_tipo']}: {row['quantidade']}")


def main():
    parser = argparse.ArgumentParser(
        description="Classifica combustivel dos veiculos e atualiza os lancamentos de abastecimento."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o resultado e desfaz as alteracoes ao final.",
    )
    args = parser.parse_args()

    conn = mysql.connector.connect(**db_config())
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT COUNT(*) AS quantidade
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'veiculos'
              AND COLUMN_NAME = 'combustivel_padrao'
            """
        )
        if int((cur.fetchone() or {}).get("quantidade") or 0) == 0:
            if args.dry_run:
                raise RuntimeError(
                    "A coluna veiculos.combustivel_padrao ainda nao existe. "
                    "Atualize a aplicacao antes de executar o dry-run."
                )
            cur.execute(
                "ALTER TABLE veiculos ADD COLUMN combustivel_padrao VARCHAR(20) DEFAULT 'diesel_500'"
            )

        print_summary(cur, "Situacao antes da migracao:")

        cur.execute(
            f"""
            UPDATE veiculos
            SET combustivel_padrao = CASE
                WHEN UPPER(TRIM(COALESCE(modelo, ''))) REGEXP
                    '(^|[^A-Z0-9])(GOL|POLO|SAVEIRO)([^A-Z0-9]|$)'
                    THEN 'flex'
                WHEN TRIM(COALESCE(nome, '')) IN ({placeholders(VEICULOS_DIESEL_S10)})
                    THEN 'diesel_s10'
                WHEN LOWER(TRIM(COALESCE(combustivel_padrao, ''))) IN (
                    {placeholders(COMBUSTIVEIS_VEICULO_VALIDOS)}
                )
                    THEN LOWER(TRIM(combustivel_padrao))
                ELSE 'diesel_500'
            END
            """,
            VEICULOS_DIESEL_S10 + COMBUSTIVEIS_VEICULO_VALIDOS,
        )
        veiculos_atualizados = cur.rowcount

        cur.execute(
            """
            UPDATE abastecimentos a
            INNER JOIN veiculos v ON v.id = a.veiculo_id
            SET a.combustivel_tipo = CASE
                WHEN LOWER(TRIM(COALESCE(a.combustivel_tipo, ''))) IN ('arla', 'arla32', 'arla 32')
                     AND v.combustivel_padrao = 'diesel_s10'
                    THEN 'arla'
                WHEN LOWER(TRIM(COALESCE(a.combustivel_tipo, ''))) IN (
                    'gasolina', 'gasolina comum', 'gasolina c', 'gasolina c comum'
                )
                    THEN 'gasolina'
                WHEN LOWER(TRIM(COALESCE(a.combustivel_tipo, ''))) IN (
                    'etanol', 'etanol comum', 'etanol hidratado',
                    'etanol hidratado comum', 'alcool', 'álcool'
                )
                    THEN 'etanol'
                WHEN v.combustivel_padrao = 'flex'
                    THEN 'gasolina'
                ELSE v.combustivel_padrao
            END
            """
        )
        abastecimentos_atualizados = cur.rowcount

        encontrados = fetch_rows(
            cur,
            f"""
            SELECT TRIM(nome) AS numero
            FROM veiculos
            WHERE TRIM(COALESCE(nome, '')) IN ({placeholders(VEICULOS_DIESEL_S10)})
            ORDER BY CAST(TRIM(nome) AS UNSIGNED)
            """,
            VEICULOS_DIESEL_S10,
        )
        numeros_encontrados = {str(row["numero"]) for row in encontrados}
        numeros_ausentes = [
            numero for numero in VEICULOS_DIESEL_S10 if numero not in numeros_encontrados
        ]

        print_summary(cur, "Situacao calculada pela migracao:")
        print(f"\nVeiculos alterados: {veiculos_atualizados}")
        print(f"Abastecimentos alterados: {abastecimentos_atualizados}")
        if numeros_ausentes:
            print("Veiculos S10 nao encontrados neste banco: " + ", ".join(numeros_ausentes))

        if args.dry_run:
            conn.rollback()
            print("\nDry-run concluido: nenhuma alteracao foi gravada.")
        else:
            conn.commit()
            print("\nMigracao concluida e gravada.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
