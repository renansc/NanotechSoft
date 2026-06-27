#!/usr/bin/env python3
"""Ferramenta local para consultas operacionais em tempo real pelo terminal."""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

try:
    import mysql.connector
except Exception:  # pragma: no cover
    mysql = None


ROOT = Path(__file__).resolve().parents[1]

FRETE_STATUS = {
    "chegada": "Chegada na empresa",
    "descarregado": "Descarregado Aguardando Carga",
    "liberado": "Liberado para Carregar",
    "carregando": "Carregando",
    "carregado": "Carregado Liberado P Viajem",
    "entregando": "Entregando",
    "retornando": "Retornando",
    "paradoVasio": "Parado (vazio)",
    "paradoCarregado": "Parado (carregado)",
}

VEHICLE_STOPWORDS = {
    "vai",
    "que",
    "tem",
    "com",
    "para",
    "pra",
    "pro",
    "em",
    "do",
    "da",
    "de",
}

AGENT_FRETE_SELECT_SQL = """
    SELECT
        f.id,
        f.nome,
        f.cidade,
        f.data_carga,
        f.status,
        f.motorista_id,
        f.entregador_id,
        f.colaborador_motorista_id,
        f.colaborador_entregador_id,
        f.veiculo_id,
        f.carga_id,
        f.observacao,
        f.km_atual,
        f.peso,
        f.qtd_entregas,
        f.created_at,
        f.updated_at,
        f.finalizado_em,
        f.arquivado,
        cm.nome AS colaborador_motorista_nome,
        ce.nome AS colaborador_entregador_nome,
        m.nome AS motorista_nome,
        e.nome AS entregador_nome,
        v.nome AS veiculo_nome,
        v.placa AS veiculo_placa,
        c.nome AS carga_nome,
        c.cidade AS carga_cidade,
        c.rota AS carga_rota,
        c.veiculo_numero AS carga_veiculo_numero,
        cil.carga_cidades AS carga_cidades,
        COALESCE(f.veiculo_id, vr.id) AS veiculo_id_resolvido,
        COALESCE(v.nome, vr.nome) AS veiculo_nome_resolvido,
        COALESCE(v.placa, vr.placa) AS veiculo_placa_resolvida
    FROM fretes f
    LEFT JOIN colaboradores cm ON f.colaborador_motorista_id = cm.id
    LEFT JOIN colaboradores ce ON f.colaborador_entregador_id = ce.id
    LEFT JOIN motoristas m ON f.motorista_id = m.id
    LEFT JOIN motoristas e ON f.entregador_id = e.id
    LEFT JOIN veiculos v ON f.veiculo_id = v.id
    LEFT JOIN cargas c ON f.carga_id = c.id
    LEFT JOIN (
        SELECT x.carga_id, GROUP_CONCAT(x.cidade ORDER BY x.primeira_linha SEPARATOR ' - ') AS carga_cidades
        FROM (
            SELECT carga_id, cidade, MIN(linha_num) AS primeira_linha
            FROM cargas_import_linhas
            WHERE TRIM(COALESCE(cidade, '')) <> ''
            GROUP BY carga_id, cidade
        ) x
        GROUP BY x.carga_id
    ) cil ON cil.carga_id = c.id
    LEFT JOIN veiculos vr ON TRIM(COALESCE(vr.nome, '')) = TRIM(COALESCE(c.veiculo_numero, ''))
        OR TRIM(COALESCE(vr.placa, '')) = TRIM(COALESCE(c.veiculo_numero, ''))
"""


def _as_str(value: object) -> str:
    return "" if value is None else str(value).strip()


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return int(default)


def _as_float_br(value: object, default: float = 0.0) -> float:
    text = _as_str(value).replace(" ", "")
    if not text:
        return float(default)
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "." in text and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    elif "," in text:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", text):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except Exception:
        return float(default)


def _fmt_decimal_br(value: object, decimals: int = 0) -> str:
    number = _as_float_br(value, 0.0)
    rendered = f"{number:,.{max(0, int(decimals))}f}"
    return rendered.replace(",", "_").replace(".", ",").replace("_", ".")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9_.\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        values[key] = value
    return values


def db_config() -> dict[str, object]:
    env = load_env()
    return {
        "host": env.get("DB_HOST") or os.environ.get("DB_HOST", "127.0.0.1"),
        "port": int(env.get("DB_PORT") or os.environ.get("DB_PORT", "3306")),
        "user": env.get("DB_USER") or os.environ.get("DB_USER", "root"),
        "password": env.get("DB_PASSWORD") or os.environ.get("DB_PASSWORD", "root123"),
        "database": env.get("DB_NAME") or os.environ.get("DB_NAME", "riobranco"),
    }


def status_label(status: object) -> str:
    key = _as_str(status)
    return FRETE_STATUS.get(key, key or "-")


def fetch_fretes() -> list[dict]:
    if mysql is None or getattr(mysql, "connector", None) is None:
        raise RuntimeError("mysql-connector-python nao esta disponivel")
    conn = mysql.connector.connect(**db_config())
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(AGENT_FRETE_SELECT_SQL + " ORDER BY f.id DESC")
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


def frete_card(frete: dict) -> dict:
    return {
        "id": frete.get("id"),
        "title": " - ".join(
            part for part in [
                _as_str(frete.get("veiculo_nome") or frete.get("carga_veiculo_numero")) and f"Caminhao {_as_str(frete.get('veiculo_nome') or frete.get('carga_veiculo_numero'))}",
                _as_str(frete.get("carga_nome")),
                _as_str(frete.get("nome")),
            ] if part
        ) or f"Frete #{frete.get('id')}",
        "status": _as_str(frete.get("status")),
        "status_label": status_label(frete.get("status")),
        "vehicle": _as_str(frete.get("veiculo_nome_resolvido") or frete.get("veiculo_nome") or frete.get("carga_veiculo_numero") or "-"),
        "plate": _as_str(frete.get("veiculo_placa_resolvida") or frete.get("veiculo_placa")),
        "driver": _as_str(frete.get("colaborador_motorista_nome") or frete.get("motorista_nome") or "-"),
        "helper": _as_str(frete.get("colaborador_entregador_nome") or frete.get("entregador_nome") or "-"),
        "load": _as_str(frete.get("carga_nome") or frete.get("nome") or "-"),
        "city": _as_str(frete.get("carga_cidade") or frete.get("cidade")),
        "route": _as_str(frete.get("carga_rota")),
        "cities": _as_str(frete.get("carga_cidades")),
        "date": _as_str(frete.get("data_carga")),
        "weight": frete.get("carga_peso_total") if frete.get("carga_peso_total") not in (None, "", 0, 0.0) else frete.get("peso"),
        "deliveries": frete.get("qtd_entregas"),
        "raw": frete,
    }


def parse_frete_message(message: str) -> dict:
    normalized = normalize(message)
    filters = {
        "city": "",
        "route": "",
        "vehicle": "",
        "status": "",
        "deliveries": None,
    }
    deliveries_match = re.search(r"\bentregas?\s+(\d+)\b|\b(\d+)\s+entregas?\b", normalized)
    if deliveries_match:
        filters["deliveries"] = _as_int(deliveries_match.group(1) or deliveries_match.group(2), 0)

    city_match = re.search(r"\b(?:para|pra|pro|em)\s+([a-z0-9][a-z0-9 ]+?)(?:\s+com\b|\s+e\b|$)", normalized)
    if city_match:
        filters["city"] = city_match.group(1).strip()

    vehicle_match = re.search(r"\b(?:caminhao|camiao|veiculo)\s+([a-z0-9-]+)\b", normalized)
    if vehicle_match:
        vehicle_token = vehicle_match.group(1).strip()
        if vehicle_token not in VEHICLE_STOPWORDS:
            filters["vehicle"] = vehicle_token

    for raw_status, label in FRETE_STATUS.items():
        if normalize(label) in normalized or normalize(raw_status) in normalized:
            filters["status"] = raw_status
            break
    return filters


def filter_fretes(cards: list[dict], *, city: str = "", route: str = "", vehicle: str = "", status: str = "", deliveries: int | None = None, query: str = "") -> list[dict]:
    city_norm = normalize(city)
    route_norm = normalize(route)
    vehicle_norm = normalize(vehicle)
    status_norm = normalize(status)
    query_norm = normalize(query)
    filtered: list[dict] = []
    for card in cards:
        raw = card.get("raw") or {}
        haystack = normalize(" ".join([
            _as_str(card.get("title")),
            _as_str(card.get("vehicle")),
            _as_str(card.get("plate")),
            _as_str(card.get("load")),
            _as_str(card.get("city")),
            _as_str(card.get("route")),
            _as_str(card.get("cities")),
            _as_str(raw.get("cidade")),
            _as_str(raw.get("carga_cidade")),
            _as_str(raw.get("carga_rota")),
        ]))
        if city_norm and city_norm not in haystack:
            continue
        if route_norm and route_norm not in haystack:
            continue
        if vehicle_norm and vehicle_norm not in haystack:
            continue
        if status_norm and status_norm not in normalize(" ".join([_as_str(card.get("status")), _as_str(card.get("status_label"))])):
            continue
        if deliveries is not None and _as_int(card.get("deliveries"), -1) != _as_int(deliveries, -2):
            continue
        if query_norm and query_norm not in haystack:
            continue
        filtered.append(card)
    return filtered


def summarize_frete(card: dict) -> str:
    city = card.get("city") or card.get("cities") or "-"
    route = card.get("route") or "-"
    return " | ".join([
        f"Frete #{_as_int(card.get('id'), 0)}",
        f"Caminhao {card.get('vehicle') or '-'}",
        f"Placa {card.get('plate') or '-'}",
        f"Carga {card.get('load') or '-'}",
        f"Cidade {city}",
        f"Rota {route}",
        f"Entregas {_as_int(card.get('deliveries'), 0)}",
        f"Status {card.get('status_label') or card.get('status') or '-'}",
    ])


def render_fretes(cards: list[dict]) -> str:
    if not cards:
        return "Nenhum frete encontrado."
    lines = []
    for card in cards:
        lines.append(
            " | ".join([
                f"Frete #{_as_int(card.get('id'), 0)}",
                f"Caminhao {card.get('vehicle') or '-'}",
                f"Placa {card.get('plate') or '-'}",
                f"Status {card.get('status_label') or card.get('status') or '-'}",
                f"Carga {card.get('load') or '-'}",
                f"Cidade {card.get('city') or '-'}",
                f"Rota {card.get('route') or '-'}",
                f"Entregas {_as_int(card.get('deliveries'), 0)}",
                f"Peso {_fmt_decimal_br(card.get('weight'), 0)}",
            ])
        )
    return "\n".join(lines)


def build_no_match_diagnostic(
    cards: list[dict],
    *,
    city: str = "",
    route: str = "",
    vehicle: str = "",
    status: str = "",
    deliveries: int | None = None,
    query: str = "",
    limit: int = 5,
) -> str:
    attempted = []
    if city:
        attempted.append(f"cidade '{city}'")
    if route:
        attempted.append(f"rota '{route}'")
    if vehicle:
        attempted.append(f"caminhao '{vehicle}'")
    if status:
        attempted.append(f"status '{status_label(status)}'")
    if deliveries is not None:
        attempted.append(f"{_as_int(deliveries, 0)} entregas")
    if query:
        attempted.append(f"termo '{query}'")

    lines = []
    if attempted:
        lines.append(f"Nenhum frete encontrado com {' e '.join(attempted)}.")
    else:
        lines.append("Nenhum frete encontrado.")

    if city:
        city_matches = filter_fretes(cards, city=city)[:limit]
        if city_matches:
            lines.append("")
            lines.append("Candidatos por cidade:")
            lines.extend(summarize_frete(card) for card in city_matches)

    if deliveries is not None:
        delivery_matches = filter_fretes(cards, deliveries=deliveries)[:limit]
        if delivery_matches:
            lines.append("")
            lines.append(f"Candidatos com {_as_int(deliveries, 0)} entregas:")
            lines.extend(summarize_frete(card) for card in delivery_matches)

    if not any(line.startswith("Candidatos") for line in lines):
        lines.append("")
        lines.append("Nenhum candidato parcial relevante encontrado.")
    return "\n".join(lines)


def cmd_fretes(args: argparse.Namespace) -> int:
    rows = fetch_fretes()
    cards = [frete_card(row) for row in rows]
    message_filters = parse_frete_message(args.message or "") if args.message else {}
    filtered = filter_fretes(
        cards,
        city=args.city or message_filters.get("city", ""),
        route=args.route or message_filters.get("route", ""),
        vehicle=args.vehicle or message_filters.get("vehicle", ""),
        status=args.status or message_filters.get("status", ""),
        deliveries=args.deliveries if args.deliveries is not None else message_filters.get("deliveries"),
        query=args.query or "",
    )
    if args.json:
        payload = {
            "filters": {
                "city": args.city or message_filters.get("city", ""),
                "route": args.route or message_filters.get("route", ""),
                "vehicle": args.vehicle or message_filters.get("vehicle", ""),
                "status": args.status or message_filters.get("status", ""),
                "deliveries": args.deliveries if args.deliveries is not None else message_filters.get("deliveries"),
                "query": args.query or "",
            },
            "results": filtered[: args.limit],
        }
        if not filtered:
            payload["diagnostic"] = build_no_match_diagnostic(
                cards,
                city=payload["filters"]["city"] or "",
                route=payload["filters"]["route"] or "",
                vehicle=payload["filters"]["vehicle"] or "",
                status=payload["filters"]["status"] or "",
                deliveries=payload["filters"]["deliveries"],
                query=payload["filters"]["query"] or "",
                limit=args.limit,
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
        return 0
    if not filtered:
        print(build_no_match_diagnostic(
            cards,
            city=args.city or message_filters.get("city", ""),
            route=args.route or message_filters.get("route", ""),
            vehicle=args.vehicle or message_filters.get("vehicle", ""),
            status=args.status or message_filters.get("status", ""),
            deliveries=args.deliveries if args.deliveries is not None else message_filters.get("deliveries"),
            query=args.query or "",
            limit=args.limit,
        ))
        return 0
    print(render_fretes(filtered[: args.limit]))
    return 0


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Consultas operacionais locais para o Continue Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fretes = subparsers.add_parser("fretes", help="Consulta fretes atuais")
    fretes.add_argument("--message", default="", help="Pergunta em linguagem natural para extrair filtros")
    fretes.add_argument("--city", default="", help="Filtra por cidade")
    fretes.add_argument("--route", default="", help="Filtra por rota")
    fretes.add_argument("--vehicle", default="", help="Filtra por numero/nome do caminhao")
    fretes.add_argument("--status", default="", help="Filtra por status")
    fretes.add_argument("--deliveries", type=int, default=None, help="Filtra pela quantidade de entregas")
    fretes.add_argument("--query", default="", help="Termo livre adicional")
    fretes.add_argument("--limit", type=int, default=10, help="Limite de resultados")
    fretes.add_argument("--json", action="store_true", help="Saida JSON")
    fretes.set_defaults(func=cmd_fretes)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
