from io import BytesIO
from textwrap import wrap

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


PAPER_FORMATS = {
    "a4": A4,
    "thermal58": (58 * mm, None),
    "thermal80": (80 * mm, None),
}


def _money(value):
    return f"R$ {float(value or 0):.2f}".replace(".", ",")


def _page_size(format_name, line_count):
    if format_name not in PAPER_FORMATS:
        raise ValueError("Formato deve ser a4, thermal58 ou thermal80.")
    width, height = PAPER_FORMATS[format_name]
    if height is None:
        height = max(100 * mm, (line_count * 4.2 + 24) * mm)
    return width, height


def _pdf(lines, format_name, title, watermark=""):
    thermal = format_name.startswith("thermal")
    max_chars = 30 if format_name == "thermal58" else (43 if thermal else 92)
    expanded_lines = []
    for raw_line in lines:
        expanded_lines.extend(wrap(str(raw_line), max_chars, break_long_words=True, replace_whitespace=False) or [""])
    width, height = _page_size(format_name, len(expanded_lines) + 4)
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    margin = 3 * mm if thermal else 16 * mm
    font_size = 7.2 if thermal else 10
    line_height = 3.8 * mm if thermal else 5.2 * mm
    y = height - margin

    pdf.setTitle(title)
    pdf.setFont("Helvetica-Bold", 9 if thermal else 15)
    pdf.drawCentredString(width / 2, y, title[:max_chars])
    y -= line_height * 1.5
    if watermark:
        pdf.setFont("Helvetica-Bold", 7 if thermal else 10)
        pdf.drawCentredString(width / 2, y, watermark[:max_chars])
        y -= line_height * 1.4
    pdf.setFont("Helvetica", font_size)
    for line in expanded_lines:
        if y < margin:
            pdf.showPage()
            pdf.setFont("Helvetica", font_size)
            y = height - margin
        pdf.drawString(margin, y, line)
        y -= line_height
    pdf.save()
    output.seek(0)
    return output


def build_order_pdf(sale, format_name="a4"):
    destination = "Balcao"
    if sale.fulfillment_type == "table":
        destination = f"Mesa: {sale.table_reference}"
    elif sale.fulfillment_type == "delivery":
        destination = f"Entrega: {sale.delivery_address}"
    lines = [
        f"Pedido: {sale.code}",
        f"Data: {sale.created_at:%d/%m/%Y %H:%M}",
        f"Cliente: {sale.customer_name}",
        f"Telefone: {sale.customer_phone or '-'}",
        destination,
        "-" * 42,
    ]
    for item in sale.items.all():
        name = item.product.name if item.product else "Item"
        lines.extend([
            name,
            f"{float(item.quantity):.3f} x {_money(item.unit_price)} = {_money(item.total_amount)}",
        ])
    lines.extend([
        "-" * 42,
        f"Subtotal: {_money(sale.subtotal_amount)}",
        f"Desconto: {_money(sale.discount_amount)}",
        f"TOTAL: {_money(sale.total_amount)}",
        f"Status: {sale.delivery_status}",
        f"Observacoes: {sale.notes or '-'}",
    ])
    return _pdf(lines, format_name, f"PEDIDO {sale.code}")


def build_fiscal_pdf(simulation, settings, format_name="a4"):
    sale = simulation.sale
    lines = [
        settings.get("FISCAL_LEGAL_NAME") or settings.get("COMPANY_NAME") or "NanoStore",
        f"CNPJ: {simulation.issuer_cnpj or settings.get('FISCAL_CNPJ', '-')}",
        f"IE: {settings.get('FISCAL_IE', '-')}",
        f"Modelo: {simulation.document_model}  Ambiente: simulacao local",
        f"Simulacao: {simulation.code}",
        f"Pedido: {sale.code}",
        f"Consumidor: {sale.customer_name}",
        "-" * 42,
    ]
    for item in sale.items.all():
        product = item.product
        lines.extend([
            product.name if product else "Item",
            f"{float(item.quantity):.3f} x {_money(item.unit_price)} = {_money(item.total_amount)}",
            f"NCM {product.ncm if product else '-'} CFOP {product.cfop if product else '-'}",
        ])
    lines.extend([
        "-" * 42,
        f"TOTAL: {_money(simulation.total_amount)}",
        f"Assinatura: {simulation.status}",
        "Documento auxiliar de simulacao.",
        "Sem chave, protocolo ou autorizacao da SEFAZ.",
    ])
    title = "DANFE NFC-e" if simulation.document_model == "65" else "DANFE NF-e"
    return _pdf(lines, format_name, title, "SIMULACAO SEM VALOR FISCAL")
