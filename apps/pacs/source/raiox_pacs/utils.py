from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    candidate = (value or "").strip()
    if not candidate:
        return None
    return date.fromisoformat(candidate)


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    candidate = (value or "").strip()
    if not candidate:
        return None
    return datetime.fromisoformat(candidate)


def format_dicom_date(value: date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    return value.strftime("%Y%m%d")


def format_dicom_time(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%H%M%S")


def clean_digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on", "sim", "s"}:
        return True
    if text in {"0", "false", "no", "n", "off", "nao", "não"}:
        return False
    return default


def slugify(value: str, fallback: str = "item") -> str:
    text = re.sub(r"[^a-z0-9_-]+", "-", (value or "").strip().lower())
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or fallback


def build_accession_number() -> str:
    stamp = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S")
    suffix = f"{uuid.uuid4().int % 100:02d}"
    return f"{stamp}{suffix}"[:16]


def build_uid(uid_root: str) -> str:
    root = (uid_root or "2.25").rstrip(".")
    return f"{root}.{uuid.uuid4().int}"


def invoice_number_for_exam(exam_id: int) -> str:
    year = datetime.now().strftime("%y")
    return f"RXF{year}{exam_id:06d}"


def invoice_number_for_order(order_id: int) -> str:
    year = datetime.now().strftime("%y")
    return f"RXO{year}{order_id:06d}"


def normalize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_json(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value
