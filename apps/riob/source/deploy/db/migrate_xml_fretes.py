#!/usr/bin/env python3
"""Reconcilia a logistica das NF-e de saida ja importadas."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from server import migrar_importacoes_xml_fretes


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Resolve o veiculo dos XMLs de saida, reaproveita fretes ativos "
            "e cria cards no Kanban quando necessario. Saidas retiradas pelo "
            "cliente ficam registradas sem frete da empresa."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Executa toda a reconciliacao e desfaz a transacao ao final.",
    )
    args = parser.parse_args()
    resultado = migrar_importacoes_xml_fretes(dry_run=args.dry_run)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
