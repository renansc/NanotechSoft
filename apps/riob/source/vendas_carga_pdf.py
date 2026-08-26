import datetime
import hashlib
import re

from pypdf import PdfReader


MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _decimal(value):
    text = str(value or "").strip()
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _parse_carga_text(text, signature, page_number=1):
    date_match = re.search(r"(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})", text, re.IGNORECASE)
    if not date_match:
        raise ValueError("Data da carga nao encontrada no PDF.")
    month = MESES.get(date_match.group(2).lower())
    if not month:
        raise ValueError("Mes da carga nao reconhecido.")
    data_ref = datetime.date(int(date_match.group(3)), month, int(date_match.group(1)))
    map_match = re.search(r"Mapa:\s*(\d+)", text, re.IGNORECASE)
    route_match = re.search(r"Rota:\s*(\d+)\s*-\s*([^\r\n]+?)(?:\s{2,}|$)", text, re.IGNORECASE | re.MULTILINE)
    if not map_match or not route_match:
        raise ValueError("Mapa ou rota nao encontrados no PDF.")
    products = []
    current_group = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        group_match = re.match(r"Grupo C\.:\s*(.+?)(?:\s{2,}|$)", line, re.IGNORECASE)
        if group_match:
            current_group = group_match.group(1).strip()
            continue
        product_match = re.match(r"(\d{4,5})\s+(.+?)\s{2,}(.+)$", line)
        if not product_match:
            continue
        tail = product_match.group(3)
        quantities = re.findall(r"(\d+(?:[.,]\d+)?)\s*(CX|PT|UN)\b", tail, re.IGNORECASE)
        if not quantities:
            continue
        products.append({
            "codigo": product_match.group(1),
            "descricao": re.sub(r"\s+", " ", product_match.group(2)).strip(),
            "grupo": current_group,
            "quantidades": [{"quantidade": _decimal(qty), "unidade": unit.upper()} for qty, unit in quantities],
        })
    cities = []
    in_cities = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if "RESUMO DAS CIDADES ATENDIDAS" in line:
            in_cities = True
            continue
        if not in_cities or not line or line.startswith("CIDADE"):
            continue
        match = re.match(r"(.+?)\s{2,}([A-Z]{2})\s+([\d.,]+)\s+(\d+)\s+([\d.,]+)$", line)
        if match:
            cities.append({"cidade": match.group(1).strip(), "uf": match.group(2), "peso": _decimal(match.group(3)), "entregas": int(match.group(4)), "volumes": _decimal(match.group(5))})
    def total(pattern):
        match = re.search(pattern, text, re.IGNORECASE)
        return _decimal(match.group(1)) if match else 0.0
    return {
        "assinatura": signature,
        "pagina": page_number,
        "data_ref": data_ref.isoformat(),
        "mapa": map_match.group(1),
        "rota_codigo": route_match.group(1),
        "rota_nome": route_match.group(2).strip(),
        "cidades": cities,
        "produtos": products,
        "peso_total": total(r"Peso Total:\s*([\d.,]+)"),
        "volumes_total": total(r"Total dos Volumes:\s*([\d.,]+)"),
        "qtd_entregas": int(total(r"N[uú]mero Entregas:\s*([\d.,]+)")),
        "valor_total": total(r"Valor Total Liquido:\s*([\d.,]+)"),
        "valor_bonificacao": total(r"Valor Bonifica[cç][aã]o:\s*([\d.,]+)"),
    }


def parse_cargas_pdf(path):
    with open(path, "rb") as pdf_file:
        raw = pdf_file.read()
    reader = PdfReader(path)
    pages = []
    page_count = len(reader.pages)
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text(extraction_mode="layout") or ""
        # Alguns geradores inserem uma folha tecnica totalmente vazia entre as
        # cargas. Ela nao representa um mapa e nao deve invalidar o PDF inteiro.
        if not text.strip():
            continue
        signature_source = raw if page_count == 1 else raw + f"#page:{index}".encode("ascii")
        pages.append(_parse_carga_text(text, hashlib.sha256(signature_source).hexdigest(), index))
    if not pages:
        raise ValueError("O PDF nao possui paginas de carga.")
    return pages


def parse_carga_pdf(path):
    return parse_cargas_pdf(path)[0]
