from __future__ import annotations

from io import BytesIO
from pathlib import Path
from textwrap import wrap
import unicodedata
from typing import Iterable
import zlib

from PIL import Image


def _ascii_text(value: object) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    return text.encode("cp1252", "replace").decode("cp1252")


def _escape_pdf_text(value: object) -> str:
    return _ascii_text(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_lines(lines: Iterable[object], width: int = 92) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        text = _ascii_text(line)
        if not text:
            wrapped.append("")
            continue
        pieces = wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [""]
        wrapped.extend(pieces)
    return wrapped


def _pdf_logo_object(logo_path: Path | None, max_width: int = 70, max_height: int = 52) -> tuple[bytes, float, float] | None:
    if not logo_path or not logo_path.exists():
        return None
    try:
        with Image.open(logo_path) as image:
            image = image.convert("RGBA")
            background = Image.new("RGBA", image.size, (255, 255, 255, 255))
            background.alpha_composite(image)
            rgb = background.convert("RGB")
            width, height = rgb.size
            scale = min(max_width / width, max_height / height, 1)
            draw_width = width * scale
            draw_height = height * scale
            raw = zlib.compress(rgb.tobytes())
            obj = (
                f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(raw)} >>\n"
                "stream\n"
            ).encode("ascii") + raw + b"\nendstream"
            return obj, draw_width, draw_height
    except Exception:
        return None


def build_text_pdf(
    title: str,
    lines: Iterable[object],
    subtitle: str | None = None,
    header_lines: Iterable[object] | None = None,
    footer_lines: Iterable[object] | None = None,
    logo_path: Path | None = None,
) -> bytes:
    page_width = 595.28
    page_height = 841.89
    margin = 36
    title_size = 14
    subtitle_size = 9
    body_size = 10
    footer_size = 8
    line_height = 13
    header_text = list(header_lines or [])
    footer_text = list(footer_lines or [])
    logo = _pdf_logo_object(logo_path)
    header_height = max(74 if header_text else 58 if subtitle else 42, 78 if logo else 0)
    body_lines_per_page = max(20, int((page_height - margin * 2 - header_height) / line_height))

    body = _wrap_lines(lines)
    if not body:
        body = [""]
    pages = [body[index : index + body_lines_per_page] for index in range(0, len(body), body_lines_per_page)]

    font_object = 3
    logo_object = 4 if logo else None
    first_page_object = 5 if logo else 4
    page_objects = []
    content_objects = []
    for index, _ in enumerate(pages, start=1):
        page_object = first_page_object + (index - 1) * 2
        content_object = page_object + 1
        page_objects.append(page_object)
        content_objects.append(content_object)

    objects: list[bytes] = []
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_objects)
    objects.append(f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {len(page_objects)} >>\nendobj\n".encode("ascii"))
    objects.append(b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj\n")
    if logo and logo_object:
        objects.append(f"{logo_object} 0 obj\n".encode("ascii") + logo[0] + b"\nendobj\n")

    safe_title = _escape_pdf_text(title)
    safe_subtitle = _escape_pdf_text(subtitle) if subtitle else ""
    for page_number, page_lines in enumerate(pages, start=1):
        content_stream_parts: list[str] = []
        y = page_height - margin - 6
        text_x = margin
        if logo and logo_object:
            _, draw_width, draw_height = logo
            logo_y = page_height - margin - draw_height + 2
            content_stream_parts.append(f"q {draw_width:.2f} 0 0 {draw_height:.2f} {margin:.2f} {logo_y:.2f} cm /Logo Do Q")
            text_x = margin + draw_width + 14
        if safe_subtitle:
            content_stream_parts.append(f"BT /F1 {subtitle_size} Tf 1 0 0 1 {text_x:.2f} {y:.2f} Tm ({safe_subtitle}) Tj ET")
            y -= 16
        for header_line in header_text:
            content_stream_parts.append(
                f"BT /F1 {subtitle_size} Tf 1 0 0 1 {text_x:.2f} {y:.2f} Tm ({_escape_pdf_text(header_line)}) Tj ET"
            )
            y -= 11
        y = page_height - margin - header_height
        content_stream_parts.append(f"BT /F1 {title_size} Tf 1 0 0 1 {margin:.2f} {y:.2f} Tm ({safe_title}) Tj ET")
        y -= 20
        for line in page_lines:
            safe_line = _escape_pdf_text(line)
            content_stream_parts.append(f"BT /F1 {body_size} Tf 1 0 0 1 {margin} {y:.2f} Tm ({safe_line}) Tj ET")
            y -= line_height
        footer_y = margin + 8
        for footer_line in footer_text:
            content_stream_parts.append(
                f"BT /F1 {footer_size} Tf 1 0 0 1 {margin:.2f} {footer_y:.2f} Tm ({_escape_pdf_text(footer_line)}) Tj ET"
            )
            footer_y -= 10
        footer = f"Pagina {page_number}/{len(pages)}"
        content_stream_parts.append(
            f"BT /F1 {footer_size} Tf 1 0 0 1 {page_width - margin - 96:.2f} {margin - 12:.2f} Tm ({_escape_pdf_text(footer)}) Tj ET"
        )
        content_stream = "\n".join(content_stream_parts).encode("cp1252", "replace")
        content_object = content_objects[page_number - 1]
        page_object = page_objects[page_number - 1]
        objects.append(
            (
                f"{page_object} 0 obj\n"
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width:.2f} {page_height:.2f}] "
                f"/Resources << /Font << /F1 {font_object} 0 R >>"
                f"{' /XObject << /Logo ' + str(logo_object) + ' 0 R >>' if logo_object else ''} >> /Contents {content_object} 0 R >>\n"
                f"endobj\n"
            ).encode("ascii")
        )
        objects.append(
            (
                f"{content_object} 0 obj\n"
                f"<< /Length {len(content_stream)} >>\nstream\n"
            ).encode("ascii")
            + content_stream
            + b"\nendstream\nendobj\n"
        )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj)

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)
