import re
import unicodedata
from decimal import Decimal, InvalidOperation


class PixPayloadError(ValueError):
    pass


def _ascii_text(value, limit):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    clean = "".join(char for char in normalized if not unicodedata.combining(char))
    clean = re.sub(r"[^A-Za-z0-9 $%*+\-./:]", "", clean)
    return " ".join(clean.upper().split())[:limit]


def normalize_pix_key(value, key_type):
    raw = str(value or "").strip()
    kind = str(key_type or "AUTO").upper()
    if not raw:
        raise PixPayloadError("Informe a chave Pix.")

    if kind == "AUTO":
        if "@" in raw:
            kind = "EMAIL"
        elif re.fullmatch(r"[0-9a-fA-F-]{36}", raw):
            kind = "ALEATORIA"
        else:
            raise PixPayloadError("Selecione se a chave numérica é telefone ou CPF/CNPJ.")

    if kind == "TELEFONE":
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("55") and len(digits) in {12, 13}:
            return f"+{digits}"
        if len(digits) in {10, 11}:
            return f"+55{digits}"
        raise PixPayloadError("Telefone Pix inválido. Informe DDD e número.")

    if kind == "CPF_CNPJ":
        key = re.sub(r"\D", "", raw)
        if len(key) not in {11, 14}:
            raise PixPayloadError("CPF/CNPJ Pix deve conter 11 ou 14 dígitos.")
        return key

    if kind == "EMAIL":
        key = raw.lower()
        if len(key) > 77 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", key):
            raise PixPayloadError("E-mail Pix inválido.")
        return key

    if kind == "ALEATORIA":
        if not re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            raw,
        ):
            raise PixPayloadError("Chave aleatória Pix inválida.")
        return raw.lower()

    raise PixPayloadError("Tipo de chave Pix inválido.")


def _tlv(tag, value):
    encoded = str(value).encode("utf-8")
    if len(encoded) > 99:
        raise PixPayloadError(f"Campo Pix {tag} excede o tamanho permitido.")
    return f"{tag}{len(encoded):02d}{value}"


def pix_crc16(value):
    crc = 0xFFFF
    for byte in value.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def build_static_pix_payload(key, key_type, amount, merchant_name, merchant_city=""):
    normalized_key = normalize_pix_key(key, key_type)
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise PixPayloadError("Valor Pix inválido.") from exc
    if not value.is_finite() or value <= 0:
        raise PixPayloadError("O valor Pix deve ser maior que zero.")

    name = _ascii_text(merchant_name, 25) or "RECEBEDOR PIX"
    city = _ascii_text(merchant_city, 15) or "NAO INFORMADA"
    merchant_account = _tlv("00", "br.gov.bcb.pix") + _tlv("01", normalized_key)
    payload = "".join((
        _tlv("00", "01"),
        _tlv("26", merchant_account),
        _tlv("52", "0000"),
        _tlv("53", "986"),
        _tlv("54", f"{value:.2f}"),
        _tlv("58", "BR"),
        _tlv("59", name),
        _tlv("60", city),
        _tlv("62", _tlv("05", "***")),
        "6304",
    ))
    return {
        "payload": payload + pix_crc16(payload),
        "key": normalized_key,
        "amount": float(value),
        "merchantName": name,
        "merchantCity": city,
    }
