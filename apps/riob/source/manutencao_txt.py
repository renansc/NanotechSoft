"""Leitor tolerante para notas de manutencao em texto ou planilha ODS.

O modulo trata o arquivo somente como dados. Ele nao interpreta instrucoes
presentes no texto e nunca tenta corrigir silenciosamente campos incertos.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import unicodedata
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree


MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 20
MAX_ROWS = 5000
MAX_FIELD_LENGTH = 2000
MAX_ODS_XML_BYTES = 8 * 1024 * 1024

ODS_NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
}
ODS_HEADER_ALIASES = {
    "fornecedor": {"local", "fornecedor", "emitente", "empresa"},
    "documento": {
        "tipoagrupado", "agrupado", "tipo", "documento", "nota", "grupo",
    },
    "veiculo": {"veiculo", "placa", "frota", "placafrota", "placaveiculo"},
    "data": {"data", "emissao", "dataemissao", "datadocumento"},
    "dia": {"dia"},
    "mes": {"mes"},
    "ano": {"ano"},
    "item": {"desc", "descricao", "item", "produto", "servico", "peca", "material"},
    "valor": {"valor", "total", "valortotal", "preco"},
    "identificador": {"id", "responsavel", "solicitante", "comprador"},
}


def _text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def _token(value):
    normalized = unicodedata.normalize("NFKD", _text(value))
    return re.sub(r"[^a-z0-9]+", "", normalized.encode("ascii", "ignore").decode().lower())


HEADER_ALIASES = {
    "documento": {
        "documento", "doc", "nota", "numerodanota", "nnota", "nf", "nfe",
        "orcamento", "numeroorcamento", "norcamento", "noorcamento",
        "ndanota", "nodanota",
    },
    "data": {"data", "emissao", "dataemissao", "datadocumento"},
    "item": {"item", "descricao", "produto", "servico", "peca", "material"},
    "valor": {"valor", "total", "valortotal", "preco"},
    "veiculo": {"placa", "frota", "placafrota", "veiculo", "placaveiculo"},
}


def decode_text(raw):
    if not isinstance(raw, (bytes, bytearray)):
        return str(raw or ""), "texto"
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return bytes(raw).decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return bytes(raw).decode("utf-8", errors="replace"), "utf-8-replace"


def parse_money(value):
    raw = _text(value).replace("R$", "").replace(" ", "")
    if not raw:
        raise ValueError("valor ausente")
    negative = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")"))
    raw = raw.strip("-()")
    raw = re.sub(r"[^0-9,.-]", "", raw)
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1:
        parts = raw.split(".")
        raw = "".join(parts[:-1]) + "." + parts[-1]
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("valor invalido") from exc
    if negative:
        result = -result
    return float(result.quantize(Decimal("0.01")))


def parse_date(value):
    raw = _text(value)
    for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError("data invalida")


def infer_supplier(filename):
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    stem = re.sub(r"^(notas?|manutencao|manutencoes)[-_ ]+", "", stem, flags=re.I)
    stem = re.sub(r"[-_]+", " ", stem)
    stem = re.sub(r"\b(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\b", "", stem, flags=re.I)
    stem = re.sub(r"\b20\d{2}\b", "", stem)
    return _text(stem).title()


def _delimiter(lines):
    candidates = ("|", ";", "\t")
    scores = {}
    sample = [line for line in lines if _text(line)][:30]
    for candidate in candidates:
        counts = [line.count(candidate) for line in sample]
        scores[candidate] = (sum(count > 0 for count in counts), sum(counts))
    selected = max(candidates, key=lambda item: scores[item])
    return selected if scores[selected][0] else "|"


def _header_map(row):
    mapped = {}
    for index, cell in enumerate(row):
        token = _token(cell)
        for field, aliases in HEADER_ALIASES.items():
            if token in aliases and field not in mapped:
                mapped[field] = index
                break
    if {"documento", "data", "item", "valor"}.issubset(mapped):
        return mapped
    return None


def _cell(row, index):
    if index is None or index >= len(row):
        return ""
    return _text(row[index])[:MAX_FIELD_LENGTH]


def _warning_codes(document):
    warnings = []
    doc = document["numero_nota"]
    if "?" in doc:
        warnings.append("Número do documento contém caractere incerto (?).")
    if not document["referencia_veiculo"]:
        warnings.append("Veículo não informado; selecione-o durante a conferência.")
    if any("legivel" in _token(item["nome_produto"]) for item in document["itens"]):
        warnings.append("Há descrição marcada como pouco legível.")
    signatures = [(item["nome_produto"].casefold(), item["valor_total"]) for item in document["itens"]]
    if len(signatures) != len(set(signatures)):
        warnings.append("Há linhas idênticas; foram preservadas para conferência.")
    return warnings


def _ods_header_map(row):
    mapped = {}
    for index, cell in enumerate(row):
        token = _token(cell)
        for field, aliases in ODS_HEADER_ALIASES.items():
            if token in aliases and field not in mapped:
                mapped[field] = index
                break
    has_date = "data" in mapped or {"dia", "mes"}.issubset(mapped)
    if {"fornecedor", "item", "valor"}.issubset(mapped) and has_date:
        return mapped
    return None


def _ods_cell_text(cell):
    text_value = _text(" ".join(cell.itertext()))
    if text_value:
        return text_value[:MAX_FIELD_LENGTH]
    for attribute in ("string-value", "date-value", "value"):
        value = cell.attrib.get(f"{{{ODS_NS['office']}}}{attribute}")
        if value not in (None, ""):
            return _text(value)[:MAX_FIELD_LENGTH]
    return ""


def _ods_nonempty_rows(content_root):
    row_number = 0
    yielded = 0
    for table in content_root.findall(".//table:table", ODS_NS):
        for row in table.findall("table:table-row", ODS_NS):
            try:
                row_repeat = int(
                    row.attrib.get(f"{{{ODS_NS['table']}}}number-rows-repeated", "1")
                )
            except ValueError:
                row_repeat = 1
            values = []
            for cell in list(row):
                if cell.tag not in {
                    f"{{{ODS_NS['table']}}}table-cell",
                    f"{{{ODS_NS['table']}}}covered-table-cell",
                }:
                    continue
                try:
                    column_repeat = int(
                        cell.attrib.get(
                            f"{{{ODS_NS['table']}}}number-columns-repeated", "1"
                        )
                    )
                except ValueError:
                    column_repeat = 1
                value = _ods_cell_text(cell)
                if not value and column_repeat > 256:
                    continue
                values.extend([value] * min(column_repeat, 256))
            while values and not values[-1]:
                values.pop()
            if not values:
                row_number += max(1, row_repeat)
                continue
            if row_repeat > MAX_ROWS:
                raise ValueError("planilha possui repetição excessiva de linhas preenchidas")
            for _ in range(max(1, row_repeat)):
                row_number += 1
                yielded += 1
                if yielded > MAX_ROWS:
                    raise ValueError(f"arquivo excede o limite de {MAX_ROWS} linhas")
                yield row_number, values


def _ods_document_year(archive):
    try:
        info = archive.getinfo("meta.xml")
        if info.file_size > MAX_ODS_XML_BYTES:
            return None
        root = ElementTree.fromstring(archive.read(info))
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile):
        return None
    values = []
    for path in (".//dc:date",):
        values.extend(_text(node.text) for node in root.findall(path, ODS_NS))
    for value in values:
        match = re.match(r"^(20\d{2})-", value)
        if match:
            return int(match.group(1))
    return None


def _ods_date(row, header, inferred_year):
    if "data" in header:
        raw_date = _cell(row, header.get("data"))
        if not raw_date:
            return "", False
        return parse_date(raw_date), False
    day_text = _cell(row, header.get("dia"))
    month_text = _cell(row, header.get("mes"))
    year_text = _cell(row, header.get("ano"))
    if not day_text and not month_text:
        return "", False
    try:
        day = int(float(day_text.replace(",", ".")))
        month = int(float(month_text.replace(",", ".")))
        year = int(float(year_text.replace(",", "."))) if year_text else inferred_year
        if year < 100:
            year += 2000
        return date(year, month, day).isoformat(), not bool(year_text)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("data invalida") from exc


def parse_maintenance_ods(raw, filename="arquivo.ods"):
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("arquivo ODS invalido")
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("arquivo excede o limite de 2 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            try:
                content_info = archive.getinfo("content.xml")
            except KeyError as exc:
                raise ValueError("planilha ODS sem content.xml") from exc
            if content_info.file_size > MAX_ODS_XML_BYTES:
                raise ValueError("conteudo XML da planilha excede o limite permitido")
            if content_info.compress_size and content_info.file_size > content_info.compress_size * 200:
                raise ValueError("compactacao da planilha excede o limite de seguranca")
            content_root = ElementTree.fromstring(archive.read(content_info))
            inferred_year = _ods_document_year(archive) or datetime.now().year
    except zipfile.BadZipFile as exc:
        raise ValueError("arquivo ODS invalido") from exc
    except ElementTree.ParseError as exc:
        raise ValueError("XML da planilha ODS invalido") from exc

    rows = list(_ods_nonempty_rows(content_root))
    header = None
    data_rows = []
    for line_number, row in rows:
        detected = _ods_header_map(row)
        if detected:
            header = detected
            continue
        if header is not None:
            data_rows.append((line_number, row))
    if header is None:
        raise ValueError(
            "cabecalho ODS não reconhecido; informe LOCAL, DIA/MES, DESC e VALOR"
        )

    groups = {}
    invalid_rows = []
    used_inferred_year = False
    source_lines = ["\t".join(row) for _, row in rows]
    source_index_by_line = {
        line_number: index + 1 for index, (line_number, _) in enumerate(rows)
    }
    for line_number, row in data_rows:
        supplier = _cell(row, header.get("fornecedor"))
        item_name = _cell(row, header.get("item"))
        vehicle = _cell(row, header.get("veiculo"))
        grouped_number = _cell(row, header.get("documento"))
        identifier = _cell(row, header.get("identificador"))
        try:
            document_date, year_was_inferred = _ods_date(row, header, inferred_year)
            value = parse_money(_cell(row, header.get("valor")))
        except ValueError as exc:
            invalid_rows.append(
                {"linha": line_number, "conteudo": " | ".join(row), "erro": str(exc)}
            )
            continue
        if not supplier or not item_name:
            invalid_rows.append(
                {
                    "linha": line_number,
                    "conteudo": " | ".join(row),
                    "erro": "fornecedor ou item ausente",
                }
            )
            continue
        used_inferred_year = used_inferred_year or year_was_inferred
        display_number = grouped_number or f"S/N L{line_number}"
        grouping_token = grouped_number or f"__linha_{line_number}"
        group_key = (
            _token(supplier),
            _token(grouping_token),
            document_date,
            _token(vehicle),
        )
        if group_key not in groups:
            signature = "\x1f".join(
                (os.path.basename(filename), supplier, display_number, document_date, vehicle)
            )
            groups[group_key] = {
                "documento_id": hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24],
                "numero_nota": display_number,
                "data_documento": document_date,
                "emitente_nome": supplier,
                "referencia_veiculo": vehicle,
                "itens": [],
                "linhas_origem": [],
                "warnings": [],
            }
            if not grouped_number:
                groups[group_key]["warnings"].append(
                    "Agrupamento não informado; esta linha foi tratada como documento individual."
                )
            if not document_date:
                groups[group_key]["warnings"].append(
                    "Data não informada; confira-a antes de salvar a manutenção."
                )
        document = groups[group_key]
        observation = f"Linha {line_number} do arquivo {os.path.basename(filename)}"
        if identifier:
            observation += f"; ID/responsável: {identifier}"
        document["itens"].append(
            {
                "item_seq": str(len(document["itens"]) + 1),
                "nome_produto": item_name,
                "quantidade": 1.0,
                "valor_unitario": value,
                "valor_total": value,
                "observacao": observation,
            }
        )
        document["linhas_origem"].append(source_index_by_line[line_number])

    documents = []
    for document in groups.values():
        document["valor_total"] = round(
            sum(item["valor_total"] for item in document["itens"]), 2
        )
        document["warnings"].extend(_warning_codes(document))
        documents.append(document)

    global_warnings = []
    if used_inferred_year:
        global_warnings.append(
            f"A planilha não informa o ano; foi usado {inferred_year}, obtido dos metadados do arquivo."
        )
    if invalid_rows:
        global_warnings.append(f"{len(invalid_rows)} linha(s) não puderam ser interpretadas.")
    suppliers = sorted({document["emitente_nome"] for document in documents})
    return {
        "arquivo": os.path.basename(filename or "arquivo.ods")[:255],
        "fornecedor": suppliers[0] if len(suppliers) == 1 else "Vários fornecedores",
        "encoding": "ODS",
        "delimitador": "planilha",
        "origem_tipo": "ods",
        "documentos": documents,
        "linhas_invalidas": invalid_rows,
        "warnings": global_warnings,
        "texto_bruto": "\n".join(source_lines),
        "meta": {
            "documentos": len(documents),
            "itens": sum(len(document["itens"]) for document in documents),
            "linhas_invalidas": len(invalid_rows),
        },
    }


def parse_maintenance_file(raw, filename="arquivo.txt"):
    extension = os.path.splitext(filename or "")[1].lower()
    if extension == ".ods":
        return parse_maintenance_ods(raw, filename)
    return parse_maintenance_text(raw, filename)


def parse_maintenance_text(raw, filename="arquivo.txt"):
    if isinstance(raw, (bytes, bytearray)) and len(raw) > MAX_FILE_BYTES:
        raise ValueError("arquivo excede o limite de 2 MB")
    text, encoding = decode_text(raw)
    if "\x00" in text:
        raise ValueError("arquivo binário não suportado")
    source_lines = text.splitlines()
    if len(source_lines) > MAX_ROWS + 100:
        raise ValueError(f"arquivo excede o limite de {MAX_ROWS} linhas")
    delimiter = _delimiter(source_lines)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter, skipinitialspace=True))
    metadata = {}
    header = None
    data_rows = []
    global_warnings = []

    for line_number, row in enumerate(rows, start=1):
        row = [_text(cell)[:MAX_FIELD_LENGTH] for cell in row]
        if not any(row):
            continue
        if len(row) == 1 and ":" in row[0]:
            key, value = row[0].split(":", 1)
            if _token(key) in {"fornecedor", "emitente", "empresa"}:
                metadata["fornecedor"] = _text(value)[:255]
                continue
        detected = _header_map(row)
        if detected:
            header = detected
            continue
        data_rows.append((line_number, row))

    if header is None:
        header = {"documento": 0, "data": 1, "item": 2, "valor": 3, "veiculo": 4}
        global_warnings.append("Cabeçalho não encontrado; colunas inferidas pela posição.")

    supplier = metadata.get("fornecedor") or infer_supplier(filename)
    groups = {}
    invalid_rows = []
    for line_number, row in data_rows:
        required_index = max(header[name] for name in ("documento", "data", "item", "valor"))
        if len(row) <= required_index:
            invalid_rows.append({"linha": line_number, "conteudo": " | ".join(row), "erro": "colunas insuficientes"})
            continue
        numero = _cell(row, header.get("documento"))
        item_name = _cell(row, header.get("item"))
        vehicle = _cell(row, header.get("veiculo"))
        try:
            date = parse_date(_cell(row, header.get("data")))
            value = parse_money(_cell(row, header.get("valor")))
        except ValueError as exc:
            invalid_rows.append({"linha": line_number, "conteudo": " | ".join(row), "erro": str(exc)})
            continue
        if not numero or not item_name:
            invalid_rows.append({"linha": line_number, "conteudo": " | ".join(row), "erro": "documento ou item ausente"})
            continue
        group_key = (numero, date, _token(vehicle))
        if group_key not in groups:
            signature = "\x1f".join((os.path.basename(filename), supplier, numero, date, vehicle))
            groups[group_key] = {
                "documento_id": hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24],
                "numero_nota": numero,
                "data_documento": date,
                "emitente_nome": supplier,
                "referencia_veiculo": vehicle,
                "itens": [],
                "linhas_origem": [],
            }
        document = groups[group_key]
        document["itens"].append({
            "item_seq": str(len(document["itens"]) + 1),
            "nome_produto": item_name,
            "quantidade": 1.0,
            "valor_unitario": value,
            "valor_total": value,
            "observacao": f"Linha {line_number} do arquivo {os.path.basename(filename)}",
        })
        document["linhas_origem"].append(line_number)

    documents = []
    for document in groups.values():
        document["valor_total"] = round(sum(item["valor_total"] for item in document["itens"]), 2)
        document["warnings"] = _warning_codes(document)
        documents.append(document)

    if invalid_rows:
        global_warnings.append(f"{len(invalid_rows)} linha(s) não puderam ser interpretadas.")
    return {
        "arquivo": os.path.basename(filename or "arquivo.txt")[:255],
        "fornecedor": supplier,
        "encoding": encoding,
        "delimitador": "TAB" if delimiter == "\t" else delimiter,
        "documentos": documents,
        "linhas_invalidas": invalid_rows,
        "warnings": global_warnings,
        "texto_bruto": text,
        "meta": {
            "documentos": len(documents),
            "itens": sum(len(document["itens"]) for document in documents),
            "linhas_invalidas": len(invalid_rows),
        },
    }
