#!/usr/bin/env python3
"""
Convert fixed-width CARGAS report TXT files into XLSX workbooks.

The reports in /media/SrvWin/CARGAS are paginated fixed-width text tables.
This script extracts the data rows, preserves the monthly columns, and writes
one XLSX file per TXT file using only the Python standard library.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape


MONTH_RE = re.compile(r"\b(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/\d{2}\b")
DATA_ROW_RE = re.compile(r"^\s*\d+")
NUMBER_RE = re.compile(r"^[\d.,]+$")


@dataclass
class ParsedTable:
    headers: list[str]
    rows: list[list[object]]


def read_text_file(path: Path) -> str:
    encodings = ("utf-8-sig", "cp1252", "latin-1")
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="replace")


def find_reference_header(lines: list[str]) -> tuple[str, str]:
    for i, line in enumerate(lines[:-1]):
        if "NrCli Razao Social" in line and re.fullmatch(r"[- ]+", lines[i + 1].strip()):
            return line, lines[i + 1]
    raise ValueError("Could not locate a table header in the TXT file")


def make_spans(dash_line: str) -> list[tuple[int, int]]:
    spans = [(match.start(), match.end()) for match in re.finditer(r"-+", dash_line)]
    if len(spans) < 3:
        raise ValueError("Header line did not expose enough column spans")
    return spans


def parse_number(value: str) -> object:
    value = value.strip()
    if not value:
        return None
    if not NUMBER_RE.match(value):
        return value
    normalized = value.replace(" ", "")
    if "." in normalized and "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        number = float(normalized)
    except ValueError:
        return value
    if number.is_integer():
        return int(number)
    return number


def parse_table(path: Path) -> ParsedTable:
    text = read_text_file(path)
    lines = text.splitlines()
    header_line, dash_line = find_reference_header(lines)
    spans = make_spans(dash_line)
    months = MONTH_RE.findall(header_line)
    if len(months) != 12:
        # Fall back to labels based on the fixed table width if the file is unusual.
        months = [f"Mes {i:02d}" for i in range(1, len(spans) - 5)]

    headers = ["NrCli", "Razao Social", "VEN", "QTD TOTAL", *months, "MEDIA", "%PART", "%ACUM."]

    rows: list[list[object]] = []
    for line in lines:
        if not DATA_ROW_RE.match(line):
            continue
        first_slice = line[spans[0][0] : spans[0][1]].strip()
        match = re.match(r"^\s*(\d+)\s+(.*)$", first_slice)
        if not match:
            continue
        nr_cli = int(match.group(1))
        razao_social = match.group(2).strip()

        row: list[object] = [nr_cli, razao_social]
        for idx, (start, end) in enumerate(spans[1:], start=1):
            raw = line[start:end].strip()
            if idx == 1:
                row.append(parse_number(raw))
            else:
                row.append(parse_number(raw))
        rows.append(row)

    return ParsedTable(headers=headers, rows=rows)


def column_letter(n: int) -> str:
    result = ""
    while n:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def row_to_xml(values: list[object], row_number: int, header: bool = False) -> str:
    cells = []
    for col_idx, value in enumerate(values, start=1):
        ref = f"{column_letter(col_idx)}{row_number}"
        if value is None:
            continue
        if isinstance(value, (int, float)) and not header:
            cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        else:
            text = escape(str(value))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>')
    return f'<row r="{row_number}">{"".join(cells)}</row>'


def build_sheet_xml(headers: list[str], rows: list[list[object]]) -> str:
    xml_rows = [row_to_xml(headers, 1, header=True)]
    for i, row in enumerate(rows, start=2):
        xml_rows.append(row_to_xml(row, i))
    sheet_data = "".join(xml_rows)
    last_col = column_letter(len(headers))
    last_row = len(rows) + 1
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews>
    <sheetView workbookViewId="0"/>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <dimension ref="A1:{last_col}{last_row}"/>
  <sheetData>{sheet_data}</sheetData>
</worksheet>
"""


def build_workbook_xml(sheet_name: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""


def build_styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font>
      <sz val="11"/>
      <name val="Calibri"/>
    </font>
    <font>
      <b/>
      <sz val="11"/>
      <name val="Calibri"/>
    </font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1">
    <border>
      <left/>
      <right/>
      <top/>
      <bottom/>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="2">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
</styleSheet>
"""


def build_content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""


def build_root_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


def build_workbook_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
"""


def build_core_props_xml(source_name: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">2026-04-06T00:00:00Z</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">2026-04-06T00:00:00Z</dcterms:modified>
  <dc:title>{escape(source_name)}</dc:title>
</cp:coreProperties>
"""


def build_app_props_xml(sheet_name: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Python</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs>
    <vt:vector size="2" baseType="variant">
      <vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>
      <vt:variant><vt:i4>1</vt:i4></vt:variant>
    </vt:vector>
  </HeadingPairs>
  <TitlesOfParts>
    <vt:vector size="1" baseType="lpstr">
      <vt:lpstr>{escape(sheet_name)}</vt:lpstr>
    </vt:vector>
  </TitlesOfParts>
</Properties>
"""


def write_xlsx(output_path: Path, table: ParsedTable, sheet_name: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", build_content_types_xml())
        zf.writestr("_rels/.rels", build_root_rels_xml())
        zf.writestr("docProps/core.xml", build_core_props_xml(output_path.stem))
        zf.writestr("docProps/app.xml", build_app_props_xml(sheet_name))
        zf.writestr("xl/workbook.xml", build_workbook_xml(sheet_name))
        zf.writestr("xl/_rels/workbook.xml.rels", build_workbook_rels_xml())
        zf.writestr("xl/styles.xml", build_styles_xml())
        zf.writestr("xl/worksheets/sheet1.xml", build_sheet_xml(table.headers, table.rows))


def convert_files(input_dir: Path, overwrite: bool = True) -> list[Path]:
    written: list[Path] = []
    for txt_path in sorted(input_dir.glob("*.txt")):
        table = parse_table(txt_path)
        xlsx_path = txt_path.with_suffix(".xlsx")
        if xlsx_path.exists() and not overwrite:
            continue
        write_xlsx(xlsx_path, table, txt_path.stem[:31] or "Dados")
        written.append(xlsx_path)
    return written


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert CARGAS TXT reports to XLSX.")
    parser.add_argument(
        "input_dir",
        nargs="?",
        default="/media/SrvWin/CARGAS",
        help="Directory containing the TXT reports.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Do not overwrite existing XLSX files.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        return 1

    written = convert_files(input_dir, overwrite=not args.no_overwrite)
    if not written:
        print("No TXT files were converted.")
        return 0

    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
