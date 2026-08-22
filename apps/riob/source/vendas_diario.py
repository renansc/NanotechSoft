import datetime
import hashlib
import os
import re


SEPARATOR_RE = re.compile(r"^\s*-=-=", re.MULTILINE)
PAGE_DATE_RE = re.compile(r"BEBIDAS WHITE RIVER LTDA\s+(\d{2}/\d{2}/\d{2})")
SELLER_RE = re.compile(r"CONFERENCIA DE PEDIDOS\s+VENDEDOR\s+(\d+)")
CLIENT_RE = re.compile(r"^\s*(\d+)\s+(.+?)\s{2,}(.+?)\s{2,}(.+?)\s*=>.*?<=", re.MULTILINE)
NEGATIVE_RE = re.compile(r"Venda Neg\. Motivo\s*:\s*(\d+)\s*=\s*([^\r\n]+)", re.IGNORECASE)
ITEM_RE = re.compile(
    r"(?<!\d)(\d{4,5})\s+(\d{1,2})\s+(\d+)\s+(\d+(?:[.,]\d+)?)\s+"
    r"([A-Z]{2})\s+(.+?)\s+(\d+[.,]\d{2})(?:\s+I\*)?(?=\s{2,}\d{4,5}\s+\d{1,2}\s+\d+\s+|\s*$)",
    re.MULTILINE,
)
ORDER_TOTAL_RE = re.compile(r"TOTAL DO PEDIDO\s+([\d.,]+)")
WEIGHT_RE = re.compile(r"PESO BRUTO TOTAL\s+([\d.,]+)Kg", re.IGNORECASE)


def intervalo_semana_iso(semana="", referencia=None):
    valor = str(semana or "").strip().upper()
    if valor:
        match = re.fullmatch(r"(\d{4})-W(\d{2})", valor)
        if not match:
            raise ValueError("Semana invalida. Use o formato AAAA-WNN.")
        try:
            segunda_iso = datetime.date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
        except ValueError as exc:
            raise ValueError("Semana invalida. Selecione uma semana valida no calendario.") from exc
        inicio = segunda_iso - datetime.timedelta(days=1)
    else:
        if isinstance(referencia, datetime.datetime):
            referencia = referencia.date()
        if not isinstance(referencia, datetime.date):
            referencia = datetime.date.today()
        dias_desde_domingo = (referencia.weekday() + 1) % 7
        inicio = referencia - datetime.timedelta(days=dias_desde_domingo)
    fim = inicio + datetime.timedelta(days=6)
    # O seletor HTML usa o numero ISO da segunda-feira, mas a operacao da
    # empresa considera a linha semanal de domingo a sabado.
    ano_iso, numero_iso, _ = (inicio + datetime.timedelta(days=1)).isocalendar()
    return inicio, fim, f"{ano_iso:04d}-W{numero_iso:02d}"


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


def read_report(path):
    with open(path, "rb") as report_file:
        raw = report_file.read()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), hashlib.sha256(raw).hexdigest()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), hashlib.sha256(raw).hexdigest()


def parse_report(text, source_name=""):
    date_match = PAGE_DATE_RE.search(text or "")
    if not date_match:
        raise ValueError("Data do relatorio nao encontrada no cabecalho.")
    report_date = datetime.datetime.strptime(date_match.group(1), "%d/%m/%y").date()
    pages = list(SELLER_RE.finditer(text))
    sellers = []
    for index, match in enumerate(pages):
        end = pages[index + 1].start() if index + 1 < len(pages) else len(text)
        sellers.append((match.start(), end, match.group(1)))

    orders = []
    current_seller = ""
    for block in SEPARATOR_RE.split(text):
        block_start = text.find(block)
        for start, end, seller_code in sellers:
            if start <= block_start < end:
                current_seller = seller_code
                break
        seller_in_block = SELLER_RE.search(block)
        if seller_in_block:
            current_seller = seller_in_block.group(1)
        client = CLIENT_RE.search(block)
        if not client:
            continue
        negative = NEGATIVE_RE.search(block)
        items = []
        for item in ITEM_RE.finditer(block):
            items.append({
                "produto_codigo": item.group(1),
                "tabela": int(item.group(2)),
                "via": int(item.group(3)),
                "quantidade": _decimal(item.group(4)),
                "unidade": item.group(5),
                "descricao": re.sub(r"\s+", " ", item.group(6)).strip(),
                "valor_unitario": _decimal(item.group(7)),
            })
        total = ORDER_TOTAL_RE.search(block)
        weight = WEIGHT_RE.search(block)
        orders.append({
            "data_ref": report_date.isoformat(),
            "vendedor_codigo": current_seller,
            "cliente_codigo": client.group(1),
            "cliente_nome": client.group(2).strip(),
            "fantasia": client.group(3).strip(),
            "cidade": client.group(4).strip(),
            "status": "negativa" if negative else "positiva",
            "motivo_codigo": negative.group(1) if negative else "",
            "motivo": negative.group(2).strip() if negative else "",
            "valor_total": _decimal(total.group(1)) if total else sum(i["quantidade"] * i["valor_unitario"] for i in items),
            "peso_bruto": _decimal(weight.group(1)) if weight else 0.0,
            "items": items,
        })
    if not orders:
        raise ValueError("Nenhum pedido foi reconhecido no arquivo.")
    return {"data_ref": report_date.isoformat(), "source_name": source_name, "orders": orders}


def discover_txt_files(directory):
    if not directory or not os.path.isdir(directory):
        return []
    return sorted(
        (os.path.join(directory, name) for name in os.listdir(directory) if name.lower().endswith(".txt")),
        key=lambda path: os.path.getmtime(path),
    )
