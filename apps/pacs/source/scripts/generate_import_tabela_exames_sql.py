from __future__ import annotations

import argparse
import json
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
DEFAULT_INPUTS = [
    Path(__file__).with_name("examesatualizado.xlsx"),
    Path(__file__).with_name("exames.xlsx"),
    Path(r"C:\Users\renan\Downloads\CadastroDePacientes.xlsx"),
    Path("/mnt/c/Users/renan/Downloads/CadastroDePacientes.xlsx"),
]
EXPECTED_SHEETS = {
    "particular": {"code": "PARTICULAR", "name": "Particular"},
    "convenios": {"code": "CONVENIOS", "name": "Convenios"},
}
TEXT_REPLACEMENTS = {
    "ARTICULÇÃO": "ARTICULAÇÃO",
    "ESCAPULO - UMERAL": "ESCAPULO-UMERAL",
}


@dataclass(frozen=True)
class PriceRow:
    sheet_row: int
    name: str
    incidence_1: Decimal
    incidence_2: Decimal
    incidence_3: Decimal


@dataclass(frozen=True)
class ExamSeedRow:
    code: str
    name: str
    modality: str
    particular: tuple[Decimal, Decimal, Decimal]
    convenios: tuple[Decimal, Decimal, Decimal]


def guess_modality(name: str) -> str:
    text = (name or "").strip().upper()
    if any(token in text for token in ("ULTRASSOM", "ULTRASSON", "USG", "ECOGRAF", "DOPPLER")):
        return "US"
    return "DR"


def locate_input_file(explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit)
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Arquivo de entrada nao encontrado: {candidate}")

    for candidate in DEFAULT_INPUTS:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Nao encontrei a planilha. Passe --input apontando para examesatualizado.xlsx."
    )


def parse_currency(value: str | None) -> Decimal:
    text = (value or "").strip()
    if not text:
        return Decimal("0.00")
    text = text.replace("R$", "").strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clean_exam_name(value: str) -> str:
    text = unicodedata.normalize("NFC", (value or "").strip())
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*-\s*DR\s*$", "", text, flags=re.IGNORECASE).strip()
    for bad, good in TEXT_REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.strip()


def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    shared_strings: list[str] = []
    for si in root.findall("main:si", NS):
        shared_strings.append("".join(t.text or "" for t in si.findall(".//main:t", NS)))
    return shared_strings


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = cell.find("main:v", NS)
    if cell_type == "s" and value_node is not None and value_node.text is not None:
        return shared_strings[int(value_node.text)]
    if cell_type == "inlineStr":
        text_node = cell.find("main:is/main:t", NS)
        return text_node.text if text_node is not None and text_node.text is not None else ""
    if value_node is not None and value_node.text is not None:
        return value_node.text
    return ""


def workbook_sheet_targets(zf: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    targets: dict[str, str] = {}
    for sheet in workbook.find("main:sheets", NS):
        rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        targets[(sheet.attrib.get("name") or "").strip().lower()] = relmap[rel_id]
    return targets


def read_price_sheet(zf: zipfile.ZipFile, target: str, shared_strings: list[str]) -> list[PriceRow]:
    sheet_root = ET.fromstring(zf.read(f"xl/{target}"))
    rows: list[PriceRow] = []
    for row in sheet_root.findall(".//main:sheetData/main:row", NS)[1:]:
        sheet_row = int(row.attrib.get("r", "0"))
        cols = {"A": "", "B": "", "C": "", "D": ""}
        for cell in row.findall("main:c", NS):
            ref = cell.attrib.get("r", "")
            col = "".join(filter(str.isalpha, ref))
            if col in cols:
                cols[col] = cell_value(cell, shared_strings).strip()

        name = clean_exam_name(cols["A"])
        if not name:
            continue
        rows.append(
            PriceRow(
                sheet_row=sheet_row,
                name=name,
                incidence_1=parse_currency(cols["B"]),
                incidence_2=parse_currency(cols["C"]),
                incidence_3=parse_currency(cols["D"]),
            )
        )
    return rows


def read_exam_seed_rows(xlsx_path: Path) -> list[ExamSeedRow]:
    with zipfile.ZipFile(xlsx_path) as zf:
        targets = workbook_sheet_targets(zf)
        shared_strings = read_shared_strings(zf)
        missing = [sheet for sheet in EXPECTED_SHEETS if sheet not in targets]
        if missing:
            raise ValueError(f"Abas obrigatorias ausentes na planilha: {', '.join(missing)}")

        particular_rows = read_price_sheet(zf, targets["particular"], shared_strings)
        convenio_rows = read_price_sheet(zf, targets["convenios"], shared_strings)

    convenio_by_row = {row.sheet_row: row for row in convenio_rows}
    seed_rows: list[ExamSeedRow] = []
    for row in particular_rows:
        convenio = convenio_by_row.get(row.sheet_row)
        if convenio is None:
            raise ValueError(f"Linha {row.sheet_row} existe em particular, mas nao existe em convenios.")
        if clean_exam_name(convenio.name).upper() != clean_exam_name(row.name).upper():
            raise ValueError(
                f"Linha {row.sheet_row} diverge entre abas: particular={row.name!r}, convenios={convenio.name!r}."
            )
        seed_rows.append(
            ExamSeedRow(
                code=f"TE-{row.sheet_row:03d}",
                name=row.name,
                modality=guess_modality(row.name),
                particular=(row.incidence_1, row.incidence_2, row.incidence_3),
                convenios=(convenio.incidence_1, convenio.incidence_2, convenio.incidence_3),
            )
        )

    if not seed_rows:
        raise ValueError("Nenhum exame encontrado na planilha.")
    return seed_rows


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def pricing_config_json() -> str:
    payload = {
        "convenios": [
            {"code": "PARTICULAR", "name": "Particular", "prices": {"1": "0.00", "2": "0.00", "3": "0.00"}},
            {"code": "CONVENIOS", "name": "Convenios", "prices": {"1": "0.00", "2": "0.00", "3": "0.00"}},
        ]
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_sql(rows: list[ExamSeedRow], source_name: str, *, include_transaction: bool) -> str:
    codes = ", ".join(sql_literal(row.code) for row in rows)
    procedure_values = ",\n".join(
        "    ("
        + ", ".join(
            [
                sql_literal(row.code),
                sql_literal(row.name),
                sql_literal(row.modality),
                money(row.particular[0]),
            ]
        )
        + ")"
        for row in rows
    )
    price_values: list[str] = []
    for row in rows:
        for convenio_code, prices in (("PARTICULAR", row.particular), ("CONVENIOS", row.convenios)):
            for index, price in enumerate(prices, start=1):
                price_values.append(
                    "    ("
                    + ", ".join(
                        [
                            sql_literal(row.code),
                            sql_literal(convenio_code),
                            str(index),
                            money(price),
                        ]
                    )
                    + ")"
                )

    lines: list[str] = []
    lines.append(f"-- Gerado a partir de {source_name}")
    lines.append("-- Atualiza nomes, modalidades e valores por incidencia.")
    lines.append("-- Procedimentos que nao estao na planilha ficam inativos para novos exames.")
    lines.append("-- Nao apaga procedimentos antigos fisicamente para preservar exames historicos.")
    lines.append("")
    if include_transaction:
        lines.append("begin;")
        lines.append("")
    lines.append("create schema if not exists raiox;")
    lines.append("")
    lines.append("insert into raiox.convenio (code, name, active)")
    lines.append("values")
    lines.append("    ('PARTICULAR', 'Particular', true),")
    lines.append("    ('CONVENIOS', 'Convenios', true)")
    lines.append("on conflict (code) do update")
    lines.append("set name = excluded.name,")
    lines.append("    active = true,")
    lines.append("    updated_at = now();")
    lines.append("")
    lines.append("with source_procedures (code, name, modality, default_price) as (")
    lines.append("  values")
    lines.append(procedure_values)
    lines.append(")")
    lines.append("insert into raiox.procedure_catalog (code, name, modality, default_price, duration_minutes, active)")
    lines.append("select code, name, modality, default_price, 20, true")
    lines.append("from source_procedures")
    lines.append("on conflict (code) do update")
    lines.append("set name = excluded.name,")
    lines.append("    modality = excluded.modality,")
    lines.append("    default_price = excluded.default_price,")
    lines.append("    active = true,")
    lines.append("    updated_at = now();")
    lines.append("")
    lines.append("update raiox.procedure_catalog")
    lines.append("set active = false,")
    lines.append("    updated_at = now()")
    lines.append(f"where code not in ({codes});")
    lines.append("")
    lines.append("with source_prices (procedure_code, convenio_code, incidences_count, price) as (")
    lines.append("  values")
    lines.append(",\n".join(price_values))
    lines.append("), resolved_prices as (")
    lines.append("  select")
    lines.append("      c.id as convenio_id,")
    lines.append("      p.id as procedure_id,")
    lines.append("      sp.convenio_code,")
    lines.append("      sp.incidences_count,")
    lines.append("      sp.price")
    lines.append("  from source_prices sp")
    lines.append("  join raiox.procedure_catalog p on p.code = sp.procedure_code")
    lines.append("  join raiox.convenio c on c.code = sp.convenio_code")
    lines.append(")")
    lines.append("insert into raiox.convenio_price (convenio_id, procedure_id, incidences_count, price, active)")
    lines.append("select convenio_id, procedure_id, incidences_count, price, true")
    lines.append("from resolved_prices")
    lines.append("on conflict (convenio_id, procedure_id, incidences_count) do update")
    lines.append("set price = excluded.price,")
    lines.append("    active = true,")
    lines.append("    updated_at = now();")
    lines.append("")
    lines.append("update raiox.convenio_price cp")
    lines.append("set active = false,")
    lines.append("    updated_at = now()")
    lines.append("where exists (")
    lines.append("    select 1 from raiox.convenio c")
    lines.append("    where c.id = cp.convenio_id and c.code in ('PARTICULAR', 'CONVENIOS')")
    lines.append(")")
    lines.append("and not exists (")
    lines.append("    select 1")
    lines.append("    from raiox.procedure_catalog p")
    lines.append("    where p.id = cp.procedure_id")
    lines.append(f"      and p.code in ({codes})")
    lines.append(");")
    lines.append("")
    lines.append("with source_prices (procedure_code, convenio_code, incidence, price) as (")
    lines.append("  values")
    lines.append(",\n".join(price_values))
    lines.append("), grouped as (")
    lines.append("  select")
    lines.append("      convenio_code,")
    lines.append("      procedure_code,")
    lines.append("      jsonb_object_agg(incidence::text, to_jsonb(price::text) order by incidence) as prices")
    lines.append("  from source_prices")
    lines.append("  group by convenio_code, procedure_code")
    lines.append("), items as (")
    lines.append("  select jsonb_agg(")
    lines.append("      jsonb_build_object(")
    lines.append("          'convenio_code', g.convenio_code,")
    lines.append("          'procedure_id', p.id,")
    lines.append("          'prices', g.prices,")
    lines.append("          'active', true")
    lines.append("      ) order by g.convenio_code, p.name")
    lines.append("  ) as payload")
    lines.append("  from grouped g")
    lines.append("  join raiox.procedure_catalog p on p.code = g.procedure_code")
    lines.append(")")
    lines.append("insert into raiox.system_settings (key, value, updated_at)")
    lines.append("select 'pricing_overrides', jsonb_build_object('items', coalesce(payload, '[]'::jsonb)), now()")
    lines.append("from items")
    lines.append("on conflict (key) do update")
    lines.append("set value = excluded.value,")
    lines.append("    updated_at = now();")
    lines.append("")
    lines.append("insert into raiox.system_settings (key, value, updated_at)")
    lines.append(f"values ('pricing_config', {sql_literal(pricing_config_json())}::jsonb, now())")
    lines.append("on conflict (key) do update")
    lines.append("set value = excluded.value,")
    lines.append("    updated_at = now();")
    lines.append("")
    if include_transaction:
        lines.append("commit;")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera SQL de importacao/atualizacao da tabela de exames.")
    parser.add_argument("--input", help="Caminho da planilha examesatualizado.xlsx")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).with_name("import_tabela_exames.sql")),
        help="Arquivo SQL usado no primeiro deploy/bootstrap",
    )
    parser.add_argument(
        "--production-output",
        default=str(Path(__file__).with_name("update_tabela_exames_producao.sql")),
        help="Arquivo SQL avulso para atualizar uma producao ja existente",
    )
    args = parser.parse_args()

    input_path = locate_input_file(args.input)
    rows = read_exam_seed_rows(input_path)
    bootstrap_sql = build_sql(rows, input_path.name, include_transaction=False)
    production_sql = build_sql(rows, input_path.name, include_transaction=True)

    output_path = Path(args.output)
    output_path.write_text(bootstrap_sql, encoding="utf-8")

    production_output_path = Path(args.production_output)
    production_output_path.write_text(production_sql, encoding="utf-8")

    print(f"SQL de bootstrap gerado em: {output_path}")
    print(f"SQL de producao gerado em: {production_output_path}")
    print(f"Exames importados: {len(rows)}")


if __name__ == "__main__":
    main()
