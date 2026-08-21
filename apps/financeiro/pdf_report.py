from __future__ import annotations

import datetime as dt
import html
from io import BytesIO
from pathlib import Path


MAX_REPORT_TITLES = 2000
MAX_REPORT_PDF_FILES = 100
MAX_REPORT_PDF_BYTES = 150 * 1024 * 1024


class FinancePdfReportError(ValueError):
    pass


def _clean_text(value, limit=500):
    return " ".join(str(value or "").split())[:limit]


def _title_description(title):
    raw = str(title.get("desc") or "")
    visible = raw.split("__GF_META__:", 1)[0].rstrip(" |\r\n")
    return _clean_text(visible or "Sem descrição")


def _date_br(value):
    try:
        return dt.date.fromisoformat(str(value or "")).strftime("%d/%m/%Y")
    except ValueError:
        return _clean_text(value) or "-"


def _money_br(value):
    try:
        formatted = f"{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        formatted = "0.00"
    return "R$ " + formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def _is_pdf_attachment(attachment):
    mime = str(attachment.get("mime") or "").lower()
    filename = str(attachment.get("path") or attachment.get("name") or "")
    return "pdf" in mime or Path(filename).suffix.lower() == ".pdf"


def _safe_attachment_path(attachments_dir, attachment):
    filename = str(attachment.get("path") or "").strip()
    label = _clean_text(attachment.get("name") or filename or "PDF sem nome", 160)
    if not filename:
        raise FinancePdfReportError(
            f'O anexo PDF "{label}" não está armazenado no servidor e não pode ser unido ao relatório.'
        )
    if Path(filename).name != filename or Path(filename).suffix.lower() != ".pdf":
        raise FinancePdfReportError(f'O anexo PDF "{label}" possui um caminho inválido.')
    path = Path(attachments_dir) / filename
    if not path.is_file():
        raise FinancePdfReportError(f'O anexo PDF "{label}" não foi encontrado no servidor.')
    with path.open("rb") as attachment_file:
        header = attachment_file.read(5)
    if path.stat().st_size <= 0 or header != b"%PDF-":
        raise FinancePdfReportError(f'O anexo PDF "{label}" está vazio ou corrompido.')
    return path, label


def collect_title_pdf_attachments(state, titles, attachments_dir):
    launches = {
        str(item.get("id")): item
        for item in state.get("lancamentos", [])
        if isinstance(item, dict) and item.get("id")
    }
    collected = []
    seen_paths = set()
    total_bytes = 0

    for title in titles:
        sources = list(title.get("anexos") or [])
        linked_launch = launches.get(str(title.get("lancId") or ""))
        if linked_launch:
            sources.extend(linked_launch.get("anexos") or [])

        for attachment in sources:
            if not isinstance(attachment, dict) or not _is_pdf_attachment(attachment):
                continue
            path, label = _safe_attachment_path(attachments_dir, attachment)
            path_key = str(path.resolve())
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            total_bytes += path.stat().st_size
            if len(collected) >= MAX_REPORT_PDF_FILES:
                raise FinancePdfReportError(
                    f"O relatório excede o limite de {MAX_REPORT_PDF_FILES} anexos PDF. Reduza o filtro."
                )
            if total_bytes > MAX_REPORT_PDF_BYTES:
                raise FinancePdfReportError(
                    "Os anexos do relatório excedem 150 MB. Reduza o período ou a quantidade de contas."
                )
            collected.append((path, label))
    return collected


def _build_report_cover(state, titles, report_type, filters, attachment_count):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output = BytesIO()
    page_size = landscape(A4)
    document = SimpleDocTemplate(
        output,
        pagesize=page_size,
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=13 * mm,
        bottomMargin=13 * mm,
        title="Contas a pagar" if report_type == "AP" else "Contas a receber",
        author="NanotechSoft",
    )
    sample = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "FinanceTitle", parent=sample["Title"], fontName="Helvetica-Bold",
        fontSize=18, leading=21, textColor=colors.HexColor("#102a43"), spaceAfter=2 * mm,
    )
    normal = ParagraphStyle(
        "FinanceNormal", parent=sample["BodyText"], fontName="Helvetica",
        fontSize=8, leading=10, textColor=colors.HexColor("#26394d"),
    )
    small = ParagraphStyle(
        "FinanceSmall", parent=normal, fontSize=7, leading=8.5,
        textColor=colors.HexColor("#526579"),
    )
    right = ParagraphStyle("FinanceRight", parent=normal, alignment=TA_RIGHT)
    right_bold = ParagraphStyle("FinanceRightBold", parent=right, fontName="Helvetica-Bold")
    heading = ParagraphStyle(
        "FinanceHeading", parent=small, fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    accounts = {
        str(item.get("id")): _clean_text(item.get("nome") or "Conta")
        for item in state.get("contas", []) if isinstance(item, dict)
    }
    categories = {
        str(item.get("id")): _clean_text(item.get("nome") or "")
        for item in state.get("categorias", []) if isinstance(item, dict)
    }
    title_text = "Contas a pagar" if report_type == "AP" else "Contas a receber"
    person_label = "Fornecedor" if report_type == "AP" else "Cliente"
    generated_at = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
    story = [
        Paragraph("NANOTECHSOFT · FINANCEIRO", small),
        Paragraph(title_text, title_style),
        Paragraph(
            f"Gerado em {generated_at} · {len(titles)} conta(s) · "
            f"{attachment_count} anexo(s) PDF incluído(s) ao final",
            small,
        ),
        Spacer(1, 3 * mm),
    ]

    filter_cells = []
    for label, value in filters:
        clean_label = html.escape(_clean_text(label, 60))
        clean_value = html.escape(_clean_text(value, 180) or "Não informado")
        filter_cells.append(Paragraph(f"<b>{clean_label}</b><br/>{clean_value}", small))
    if filter_cells:
        while len(filter_cells) % 4:
            filter_cells.append(Paragraph("", small))
        filter_table = Table(
            [filter_cells[index:index + 4] for index in range(0, len(filter_cells), 4)],
            colWidths=[46 * mm] * 4,
        )
        filter_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f7fa")),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d5df")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8e1e9")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.extend([filter_table, Spacer(1, 4 * mm)])

    rows = [[
        Paragraph("Venc.", heading), Paragraph("Conta", heading),
        Paragraph("Etiquetas", heading), Paragraph(person_label, heading),
        Paragraph("Descrição", heading), Paragraph("Valor", heading),
        Paragraph("Status", heading),
    ]]
    total = 0.0
    for title in titles:
        category_ids = title.get("categoriaIds") if isinstance(title.get("categoriaIds"), list) else []
        if not category_ids and title.get("categoriaId"):
            category_ids = [title.get("categoriaId")]
        category_text = ", ".join(
            categories.get(str(category_id), "") for category_id in category_ids
            if categories.get(str(category_id), "")
        ) or "-"
        try:
            total += float(title.get("valor") or 0)
        except (TypeError, ValueError):
            pass
        status = {
            "ABERTO": "Em aberto", "BAIXADO": "Baixado", "CANCELADO": "Cancelado"
        }.get(str(title.get("status") or "ABERTO").upper(), _clean_text(title.get("status")) or "-")
        rows.append([
            Paragraph(html.escape(_date_br(title.get("vencimento"))), normal),
            Paragraph(html.escape(accounts.get(str(title.get("contaId")), "-")), normal),
            Paragraph(html.escape(category_text), small),
            Paragraph(html.escape(_clean_text(title.get("pessoa")) or "-"), normal),
            Paragraph(html.escape(_title_description(title)), normal),
            Paragraph(html.escape(_money_br(title.get("valor"))), right_bold),
            Paragraph(html.escape(status), normal),
        ])

    if len(rows) == 1:
        rows.append([Paragraph("Nenhuma conta encontrada para os filtros informados.", normal)] + [""] * 6)

    table = Table(
        rows,
        repeatRows=1,
        colWidths=[18 * mm, 28 * mm, 31 * mm, 35 * mm, 72 * mm, 25 * mm, 23 * mm],
        hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#174f75")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd7e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([
        table,
        Spacer(1, 3 * mm),
        Table(
            [[Paragraph(f"{len(titles)} conta(s) apresentada(s)", normal),
              Paragraph(f"<b>Total apresentado: {html.escape(_money_br(total))}</b>", right)]],
            colWidths=[116 * mm, 116 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef4f8")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#afc1cf")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]),
        ),
    ])

    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#607487"))
        canvas.drawString(10 * mm, 7 * mm, "NanotechSoft · Financeiro")
        canvas.drawRightString(page_size[0] - 10 * mm, 7 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    output.seek(0)
    return output


def build_finance_titles_pdf(state, titles, report_type, filters, attachments_dir):
    if report_type not in {"AP", "AR"}:
        raise FinancePdfReportError("Tipo de relatório financeiro inválido.")
    if len(titles) > MAX_REPORT_TITLES:
        raise FinancePdfReportError(
            f"O relatório excede o limite de {MAX_REPORT_TITLES} contas. Reduza o filtro."
        )

    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.errors import PdfReadError
    except ModuleNotFoundError as exc:
        raise RuntimeError("Dependências de geração de PDF não instaladas.") from exc

    attachments = collect_title_pdf_attachments(state, titles, attachments_dir)
    report = _build_report_cover(state, titles, report_type, filters, len(attachments))
    writer = PdfWriter()

    for page in PdfReader(report, strict=False).pages:
        writer.add_page(page)

    for path, label in attachments:
        try:
            reader = PdfReader(path, strict=False)
            if reader.is_encrypted and not reader.decrypt(""):
                raise FinancePdfReportError(
                    f'O anexo PDF "{label}" possui senha e não pode ser unido ao relatório.'
                )
            if not reader.pages:
                raise FinancePdfReportError(f'O anexo PDF "{label}" não possui páginas.')
            for page in reader.pages:
                writer.add_page(page)
        except FinancePdfReportError:
            raise
        except (PdfReadError, OSError, ValueError) as exc:
            raise FinancePdfReportError(
                f'O anexo PDF "{label}" está corrompido e não pode ser unido ao relatório.'
            ) from exc

    writer.add_metadata({
        "/Title": "Contas a pagar" if report_type == "AP" else "Contas a receber",
        "/Author": "NanotechSoft",
    })
    output = BytesIO()
    writer.write(output)
    output.seek(0)
    return output, len(attachments)
