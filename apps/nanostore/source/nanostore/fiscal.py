import base64
import hashlib
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa, padding
from cryptography.hazmat.primitives.serialization import pkcs12


SIMULATION_NAMESPACE = "urn:nanostore:fiscal-simulator:v1"
ET.register_namespace("", SIMULATION_NAMESPACE)


def _utc_datetime(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _certificate_dates(certificate):
    not_before = getattr(certificate, "not_valid_before_utc", None) or _utc_datetime(certificate.not_valid_before)
    not_after = getattr(certificate, "not_valid_after_utc", None) or _utc_datetime(certificate.not_valid_after)
    return not_before, not_after


def _subject_value(certificate, oid_name):
    for attribute in certificate.subject:
        if attribute.oid._name == oid_name:
            return attribute.value
    return ""


def _cnpj_from_common_name(common_name):
    matches = re.findall(r"\d{14}", common_name or "")
    return matches[-1] if matches else ""


def load_fiscal_identity(path=None, password=None):
    certificate_path = Path(path or os.environ.get("NANOSTORE_FISCAL_CERT_PATH", "")).expanduser()
    configured = bool(str(certificate_path)) and str(certificate_path) != "."
    if not configured:
        raise RuntimeError("Certificado fiscal nao configurado neste ambiente.")
    if not certificate_path.is_file():
        raise RuntimeError("Arquivo do certificado fiscal nao encontrado.")

    raw_password = password if password is not None else os.environ.get("NANOSTORE_FISCAL_CERT_PASSWORD", "")
    password_bytes = str(raw_password).encode("utf-8") if raw_password else None
    try:
        private_key, certificate, chain = pkcs12.load_key_and_certificates(certificate_path.read_bytes(), password_bytes)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Nao foi possivel abrir o certificado fiscal. Verifique a senha.") from exc
    if private_key is None or certificate is None:
        raise RuntimeError("O arquivo fiscal nao contem certificado e chave privada.")

    common_name = _subject_value(certificate, "commonName")
    not_before, not_after = _certificate_dates(certificate)
    now = datetime.now(timezone.utc)
    fingerprint = certificate.fingerprint(hashes.SHA256()).hex().upper()
    return {
        "path": certificate_path,
        "file_name": certificate_path.name,
        "private_key": private_key,
        "certificate": certificate,
        "chain": chain or [],
        "holder": common_name,
        "cnpj": _cnpj_from_common_name(common_name),
        "serial_number": format(certificate.serial_number, "X"),
        "fingerprint": fingerprint,
        "not_before": not_before,
        "not_after": not_after,
        "valid_now": not_before <= now <= not_after,
        "expired": now > not_after,
    }


def fiscal_certificate_status():
    try:
        identity = load_fiscal_identity()
    except RuntimeError as exc:
        return {
            "configured": False,
            "ready_for_simulation": False,
            "valid_for_transmission": False,
            "error": str(exc),
        }
    return {
        "configured": True,
        "ready_for_simulation": True,
        "valid_for_transmission": identity["valid_now"],
        "expired": identity["expired"],
        "file_name": identity["file_name"],
        "holder": identity["holder"],
        "cnpj": identity["cnpj"],
        "serial_number": identity["serial_number"],
        "fingerprint": identity["fingerprint"],
        "not_before": identity["not_before"].isoformat(),
        "not_after": identity["not_after"].isoformat(),
        "error": "",
    }


def _money(value):
    return f"{Decimal(value or 0).quantize(Decimal('0.01')):.2f}"


def _quantity(value):
    return f"{Decimal(value or 0).quantize(Decimal('0.001')):.3f}"


def _sign(private_key, payload):
    if isinstance(private_key, rsa.RSAPrivateKey):
        return "RSA-SHA256", private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    if isinstance(private_key, ec.EllipticCurvePrivateKey):
        return "ECDSA-SHA256", private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        return "Ed25519", private_key.sign(payload)
    raise RuntimeError("Tipo de chave privada nao suportado pelo simulador.")


def _verify(public_key, algorithm, signature, payload):
    if algorithm == "RSA-SHA256":
        public_key.verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
    elif algorithm == "ECDSA-SHA256":
        public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
    elif algorithm == "Ed25519":
        public_key.verify(signature, payload)
    else:
        raise RuntimeError("Algoritmo de assinatura desconhecido.")


def build_signed_simulation(sale, document_model="65", identity=None):
    model = str(document_model or "65").strip()
    if model not in {"55", "65"}:
        raise ValueError("Modelo fiscal deve ser 55 ou 65.")
    if not sale.get("items"):
        raise ValueError("A venda precisa ter ao menos um item para faturar.")

    identity = identity or load_fiscal_identity()
    simulation_code = f"SIM-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:8].upper()}"
    root = ET.Element(
        f"{{{SIMULATION_NAMESPACE}}}simulacaoFiscal",
        {"versao": "1.0", "ambiente": "local", "semValorFiscal": "true"},
    )
    ET.SubElement(root, "codigo").text = simulation_code
    ET.SubElement(root, "modelo").text = model
    ET.SubElement(root, "geradoEm").text = datetime.now(timezone.utc).isoformat()

    issuer = ET.SubElement(root, "emitente")
    issuer_data = sale.get("issuer") or {}
    ET.SubElement(issuer, "razaoSocial").text = str(issuer_data.get("FISCAL_LEGAL_NAME") or "")
    ET.SubElement(issuer, "cnpj").text = str(issuer_data.get("FISCAL_CNPJ") or identity["cnpj"])
    ET.SubElement(issuer, "inscricaoEstadual").text = str(issuer_data.get("FISCAL_IE") or "")
    ET.SubElement(issuer, "uf").text = str(issuer_data.get("FISCAL_UF") or "")
    ET.SubElement(issuer, "codigoMunicipio").text = str(issuer_data.get("FISCAL_CITY_CODE") or "")
    ET.SubElement(issuer, "crt").text = str(issuer_data.get("FISCAL_CRT") or "")
    ET.SubElement(issuer, "titularCertificado").text = identity["holder"]

    sale_node = ET.SubElement(root, "venda", {"codigo": str(sale.get("code") or "")})
    ET.SubElement(sale_node, "cliente").text = str(sale.get("customer_name") or "Consumidor")
    ET.SubElement(sale_node, "canal").text = str(sale.get("source_channel") or "balcao")
    items_node = ET.SubElement(sale_node, "itens")
    for index, item in enumerate(sale["items"], start=1):
        item_node = ET.SubElement(items_node, "item", {"numero": str(index)})
        ET.SubElement(item_node, "sku").text = str(item.get("sku") or "")
        ET.SubElement(item_node, "descricao").text = str(item.get("product_name") or "")
        ET.SubElement(item_node, "lote").text = str(item.get("lot_code") or "")
        ET.SubElement(item_node, "quantidade").text = _quantity(item.get("quantity"))
        ET.SubElement(item_node, "valorUnitario").text = _money(item.get("unit_price"))
        ET.SubElement(item_node, "desconto").text = _money(item.get("discount_amount"))
        ET.SubElement(item_node, "valorTotal").text = _money(item.get("total_amount"))
        taxes = ET.SubElement(item_node, "tributacao")
        for tag, key in (
            ("ncm", "ncm"), ("cest", "cest"), ("cfop", "cfop"), ("origem", "origin"),
            ("cstIcmsCsosn", "icms_cst"), ("cstPis", "pis_cst"), ("cstCofins", "cofins_cst"),
            ("unidadeTributavel", "tax_unit"), ("gtinTributavel", "gtin_taxable"),
            ("codigoBeneficio", "benefit_code"), ("codigoAnvisa", "anvisa_code"),
            ("cstIbsCbs", "ibs_cbs_cst"), ("classificacaoTributaria", "tax_classification"),
        ):
            ET.SubElement(taxes, tag).text = str(item.get(key) or "")
        ET.SubElement(taxes, "precoMaximoConsumidor").text = _money(item.get("max_consumer_price"))
        ET.SubElement(taxes, "aliquotaIbsUf").text = str(item.get("ibs_uf_rate") or 0)
        ET.SubElement(taxes, "aliquotaIbsMunicipio").text = str(item.get("ibs_mun_rate") or 0)
        ET.SubElement(taxes, "aliquotaCbs").text = str(item.get("cbs_rate") or 0)

    totals = ET.SubElement(sale_node, "totais")
    ET.SubElement(totals, "subtotal").text = _money(sale.get("subtotal_amount"))
    ET.SubElement(totals, "desconto").text = _money(sale.get("discount_amount"))
    ET.SubElement(totals, "total").text = _money(sale.get("total_amount"))

    certificate_node = ET.SubElement(root, "certificado")
    ET.SubElement(certificate_node, "serial").text = identity["serial_number"]
    ET.SubElement(certificate_node, "fingerprintSHA256").text = identity["fingerprint"]
    ET.SubElement(certificate_node, "validoAte").text = identity["not_after"].isoformat()
    ET.SubElement(certificate_node, "validoNoMomentoDaSimulacao").text = "true" if identity["valid_now"] else "false"

    unsigned_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    algorithm, signature = _sign(identity["private_key"], unsigned_xml)
    _verify(identity["certificate"].public_key(), algorithm, signature, unsigned_xml)

    signature_node = ET.SubElement(root, "assinatura", {"algoritmo": algorithm, "verificada": "true"})
    ET.SubElement(signature_node, "digestSHA256").text = hashlib.sha256(unsigned_xml).hexdigest().upper()
    ET.SubElement(signature_node, "valor").text = base64.b64encode(signature).decode("ascii")

    return {
        "code": simulation_code,
        "document_model": model,
        "issuer_cnpj": identity["cnpj"],
        "certificate_serial": identity["serial_number"],
        "certificate_fingerprint": identity["fingerprint"],
        "certificate_valid": identity["valid_now"],
        "status": "signed_simulation" if identity["valid_now"] else "signed_expired_certificate",
        "xml": ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8"),
    }
