import base64
import os
import re
import secrets
import ssl
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from lxml import etree

from .fiscal import load_fiscal_identity
from .tax import valid_gtin


NFE_NS = "http://www.portalfiscal.inf.br/nfe"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"
SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
AUTHORIZATION_URLS = {
    "PR": "https://homologacao.nfe.sefa.pr.gov.br/nfe/NFeAutorizacao4",
}
AUTHORIZATION_ACTION = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4/nfeAutorizacaoLote"
HOMOLOGATION_RECIPIENT_NAME = "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _digits(value):
    return "".join(char for char in str(value or "") if char.isdigit())


def _decimal(value):
    return Decimal(str(value or 0))


def _money(value):
    return f"{_decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _quantity(value):
    return f"{_decimal(value).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):.4f}"


def _unit_price(value):
    return f"{_decimal(value).quantize(Decimal('0.0000000001'), rounding=ROUND_HALF_UP):.10f}"


def _text(parent, tag, value):
    node = etree.SubElement(parent, f"{{{NFE_NS}}}{tag}")
    node.text = str(value)
    return node


def _required_digits(value, length, label):
    normalized = _digits(value)
    if len(normalized) != length:
        raise ValueError(f"{label} deve conter {length} digitos.")
    return normalized


def _valid_cpf(value):
    digits = _digits(value)
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(digits[index]) * (size + 1 - index) for index in range(size))
        check = (total * 10 % 11) % 10
        if check != int(digits[size]):
            return False
    return True


def _valid_cnpj(value):
    digits = _digits(value)
    if len(digits) != 14 or len(set(digits)) == 1:
        return False
    for size, weights in (
        (12, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
        (13, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
    ):
        remainder = sum(int(digits[index]) * weights[index] for index in range(size)) % 11
        check = 0 if remainder < 2 else 11 - remainder
        if check != int(digits[size]):
            return False
    return True


def access_key_check_digit(base_key):
    if not re.fullmatch(r"\d{43}", str(base_key or "")):
        raise ValueError("Base da chave da NF-e deve conter 43 digitos.")
    weight = 2
    total = 0
    for digit in reversed(base_key):
        total += int(digit) * weight
        weight = 2 if weight == 9 else weight + 1
    remainder = total % 11
    return 0 if remainder in {0, 1} else 11 - remainder


def build_access_key(*, issued_at, cnpj, series, number, numeric_code):
    base = (
        "41"
        + issued_at.strftime("%y%m")
        + _required_digits(cnpj, 14, "CNPJ do emitente")
        + "55"
        + f"{int(series):03d}"
        + f"{int(number):09d}"
        + "1"
        + f"{int(numeric_code):08d}"
    )
    return base + str(access_key_check_digit(base))


def _validate_payload(payload, identity):
    issuer = payload.get("issuer") or {}
    customer = payload.get("customer") or {}
    errors = []
    issuer_cnpj = _digits(issuer.get("FISCAL_CNPJ"))
    if not _valid_cnpj(issuer_cnpj):
        errors.append("CNPJ do emitente e invalido.")
    if issuer_cnpj != identity["cnpj"]:
        errors.append("O CNPJ do emitente deve ser igual ao CNPJ do certificado A1.")
    required_issuer = {
        "FISCAL_LEGAL_NAME": "razao social",
        "FISCAL_IE": "IE",
        "FISCAL_ADDRESS": "logradouro",
        "FISCAL_ADDRESS_NUMBER": "numero",
        "FISCAL_NEIGHBORHOOD": "bairro",
        "FISCAL_CITY": "municipio",
        "FISCAL_CITY_CODE": "codigo IBGE",
        "FISCAL_UF": "UF",
        "FISCAL_POSTAL_CODE": "CEP",
    }
    for key, label in required_issuer.items():
        if not str(issuer.get(key) or "").strip():
            errors.append(f"Emitente sem {label}.")
    if str(issuer.get("FISCAL_CRT") or "").strip() != "1":
        errors.append("Esta primeira homologacao aceita somente emitente CRT 1 (Simples Nacional).")
    if str(issuer.get("FISCAL_UF") or "").strip().upper() != "PR":
        errors.append("Esta integracao transmite somente emitentes do Parana para a SEFAZ PR.")
    if len(_digits(issuer.get("FISCAL_CITY_CODE"))) != 7 or len(_digits(issuer.get("FISCAL_POSTAL_CODE"))) != 8:
        errors.append("Codigo IBGE ou CEP do emitente e invalido.")

    document = _digits(customer.get("document"))
    if not (_valid_cpf(document) if len(document) == 11 else _valid_cnpj(document)):
        errors.append("Cliente deve ter CPF ou CNPJ valido para NF-e 55.")
    for key, label in (
        ("address", "logradouro"), ("address_number", "numero"), ("neighborhood", "bairro"),
        ("city", "municipio"), ("city_code", "codigo IBGE"), ("state", "UF"),
        ("postal_code", "CEP"),
    ):
        if not str(customer.get(key) or "").strip():
            errors.append(f"Cliente sem {label}.")
    indicator = str(customer.get("state_registration_indicator") or "9").strip()
    if indicator not in {"1", "2", "9"}:
        errors.append("Indicador de IE do cliente deve ser 1, 2 ou 9.")
    if indicator == "1" and not _digits(customer.get("state_registration")):
        errors.append("Cliente contribuinte deve ter inscricao estadual.")
    if len(_digits(customer.get("city_code"))) != 7 or len(_digits(customer.get("postal_code"))) != 8:
        errors.append("Codigo IBGE ou CEP do cliente e invalido.")

    items = payload.get("items") or []
    if not items:
        errors.append("A venda precisa ter ao menos um item.")
    for index, item in enumerate(items, start=1):
        prefix = f"Item {index} ({item.get('sku') or 'sem SKU'})"
        if not re.fullmatch(r"\d{8}", _digits(item.get("ncm"))):
            errors.append(f"{prefix}: NCM deve conter 8 digitos.")
        cfop = str(item.get("cfop") or "")
        if not re.fullmatch(r"[56]\d{3}", cfop):
            errors.append(f"{prefix}: CFOP deve ser de saida.")
        elif customer.get("state", "").upper() == issuer.get("FISCAL_UF", "").upper() and not cfop.startswith("5"):
            errors.append(f"{prefix}: operacao interna deve usar CFOP iniciado por 5.")
        elif customer.get("state", "").upper() != issuer.get("FISCAL_UF", "").upper() and not cfop.startswith("6"):
            errors.append(f"{prefix}: operacao interestadual deve usar CFOP iniciado por 6.")
        if str(item.get("icms_cst") or "") not in {"102", "500"}:
            errors.append(f"{prefix}: homologacao inicial aceita somente CSOSN 102 ou 500.")
        if str(item.get("pis_cst") or "") != "49" or str(item.get("cofins_cst") or "") != "49":
            errors.append(f"{prefix}: homologacao inicial aceita somente PIS/COFINS CST 49.")
        if _decimal(item.get("quantity")) <= 0 or _decimal(item.get("unit_price")) < 0:
            errors.append(f"{prefix}: quantidade ou valor invalido.")
    if errors:
        raise ValueError("Cadastro fiscal incompleto: " + " | ".join(dict.fromkeys(errors)))


def _build_inf_nfe(payload, identity, *, series, number, issued_at, numeric_code):
    _validate_payload(payload, identity)
    issuer = payload["issuer"]
    customer = payload["customer"]
    access_key = build_access_key(
        issued_at=issued_at,
        cnpj=issuer["FISCAL_CNPJ"],
        series=series,
        number=number,
        numeric_code=numeric_code,
    )
    nfe = etree.Element(f"{{{NFE_NS}}}NFe", nsmap={None: NFE_NS})
    inf_nfe = etree.SubElement(nfe, f"{{{NFE_NS}}}infNFe", Id=f"NFe{access_key}", versao="4.00")

    ide = etree.SubElement(inf_nfe, f"{{{NFE_NS}}}ide")
    for tag, value in (
        ("cUF", "41"), ("cNF", f"{numeric_code:08d}"),
        ("natOp", str(payload.get("operation_nature") or "VENDA DE MERCADORIA")),
        ("mod", "55"), ("serie", series), ("nNF", number), ("dhEmi", issued_at.isoformat(timespec="seconds")),
        ("tpNF", "1"), ("idDest", "1" if customer["state"].upper() == issuer["FISCAL_UF"].upper() else "2"),
        ("cMunFG", _digits(issuer["FISCAL_CITY_CODE"])), ("tpImp", "1"), ("tpEmis", "1"),
        ("cDV", access_key[-1]), ("tpAmb", "2"), ("finNFe", "1"),
        ("indFinal", "1" if len(_digits(customer["document"])) == 11 else "0"),
        ("indPres", "1"), ("indIntermed", "0"), ("procEmi", "0"), ("verProc", "NanoStore 1.0"),
    ):
        _text(ide, tag, value)

    emit = etree.SubElement(inf_nfe, f"{{{NFE_NS}}}emit")
    _text(emit, "CNPJ", _digits(issuer["FISCAL_CNPJ"]))
    _text(emit, "xNome", issuer["FISCAL_LEGAL_NAME"])
    if issuer.get("FISCAL_TRADE_NAME"):
        _text(emit, "xFant", issuer["FISCAL_TRADE_NAME"])
    address = etree.SubElement(emit, f"{{{NFE_NS}}}enderEmit")
    for tag, value in (
        ("xLgr", issuer["FISCAL_ADDRESS"]), ("nro", issuer["FISCAL_ADDRESS_NUMBER"]),
        ("xBairro", issuer["FISCAL_NEIGHBORHOOD"]), ("cMun", _digits(issuer["FISCAL_CITY_CODE"])),
        ("xMun", issuer["FISCAL_CITY"]), ("UF", issuer["FISCAL_UF"].upper()),
        ("CEP", _digits(issuer["FISCAL_POSTAL_CODE"])), ("cPais", "1058"), ("xPais", "BRASIL"),
    ):
        _text(address, tag, value)
    if _digits(issuer.get("FISCAL_PHONE")):
        _text(address, "fone", _digits(issuer["FISCAL_PHONE"]))
    _text(emit, "IE", _digits(issuer["FISCAL_IE"]))
    _text(emit, "CRT", "1")

    dest = etree.SubElement(inf_nfe, f"{{{NFE_NS}}}dest")
    document = _digits(customer["document"])
    _text(dest, "CPF" if len(document) == 11 else "CNPJ", document)
    _text(dest, "xNome", HOMOLOGATION_RECIPIENT_NAME)
    dest_address = etree.SubElement(dest, f"{{{NFE_NS}}}enderDest")
    for tag, value in (
        ("xLgr", customer["address"]), ("nro", customer["address_number"]),
        ("xBairro", customer["neighborhood"]), ("cMun", _digits(customer["city_code"])),
        ("xMun", customer["city"]), ("UF", customer["state"].upper()),
        ("CEP", _digits(customer["postal_code"])), ("cPais", "1058"), ("xPais", "BRASIL"),
    ):
        _text(dest_address, tag, value)
    if _digits(customer.get("phone")):
        _text(dest_address, "fone", _digits(customer["phone"]))
    indicator = str(customer.get("state_registration_indicator") or "9")
    _text(dest, "indIEDest", indicator)
    if indicator == "1":
        _text(dest, "IE", _digits(customer["state_registration"]))

    product_total = Decimal("0")
    discount_total = Decimal("0")
    for index, item in enumerate(payload["items"], start=1):
        det = etree.SubElement(inf_nfe, f"{{{NFE_NS}}}det", nItem=str(index))
        prod = etree.SubElement(det, f"{{{NFE_NS}}}prod")
        barcode = _digits(item.get("barcode"))
        taxable_barcode = str(item.get("gtin_taxable") or "SEM GTIN").strip().upper()
        if not valid_gtin(barcode):
            barcode = "SEM GTIN"
        if not valid_gtin(taxable_barcode):
            taxable_barcode = "SEM GTIN"
        line_total = _decimal(item["total_amount"])
        line_discount = _decimal(item.get("discount_amount"))
        product_total += line_total + line_discount
        discount_total += line_discount
        product_fields = (
            ("cProd", item["sku"]), ("cEAN", barcode), ("xProd", item["product_name"]),
            ("NCM", _digits(item["ncm"])), ("CEST", _digits(item.get("cest"))) if item.get("cest") else None,
            ("CFOP", item["cfop"]), ("uCom", str(item.get("unit") or "UN").upper()),
            ("qCom", _quantity(item["quantity"])), ("vUnCom", _unit_price(item["unit_price"])),
            ("vProd", _money(line_total + line_discount)), ("cEANTrib", taxable_barcode),
            ("uTrib", str(item.get("tax_unit") or "UN").upper()), ("qTrib", _quantity(item["quantity"])),
            ("vUnTrib", _unit_price(item["unit_price"])),
            ("vDesc", _money(line_discount)) if line_discount else None, ("indTot", "1"),
        )
        for field in product_fields:
            if field:
                _text(prod, field[0], field[1])
        imposto = etree.SubElement(det, f"{{{NFE_NS}}}imposto")
        icms = etree.SubElement(imposto, f"{{{NFE_NS}}}ICMS")
        csosn = str(item.get("icms_cst") or "")
        icms_group = etree.SubElement(icms, f"{{{NFE_NS}}}ICMSSN{csosn}")
        _text(icms_group, "orig", item.get("origin") or "0")
        _text(icms_group, "CSOSN", csosn)
        pis = etree.SubElement(imposto, f"{{{NFE_NS}}}PIS")
        pis_other = etree.SubElement(pis, f"{{{NFE_NS}}}PISOutr")
        for tag, value in (("CST", "49"), ("vBC", "0.00"), ("pPIS", "0.0000"), ("vPIS", "0.00")):
            _text(pis_other, tag, value)
        cofins = etree.SubElement(imposto, f"{{{NFE_NS}}}COFINS")
        cofins_other = etree.SubElement(cofins, f"{{{NFE_NS}}}COFINSOutr")
        for tag, value in (("CST", "49"), ("vBC", "0.00"), ("pCOFINS", "0.0000"), ("vCOFINS", "0.00")):
            _text(cofins_other, tag, value)
        _text(det, "vItem", _money(line_total))

    total = etree.SubElement(inf_nfe, f"{{{NFE_NS}}}total")
    icms_total = etree.SubElement(total, f"{{{NFE_NS}}}ICMSTot")
    total_values = {
        "vBC": 0, "vICMS": 0, "vICMSDeson": 0, "vFCP": 0, "vBCST": 0, "vST": 0,
        "vFCPST": 0, "vFCPSTRet": 0, "vProd": product_total, "vFrete": 0, "vSeg": 0,
        "vDesc": discount_total, "vII": 0, "vIPI": 0, "vIPIDevol": 0, "vPIS": 0,
        "vCOFINS": 0, "vOutro": 0, "vNF": payload["total_amount"],
    }
    for tag, value in total_values.items():
        _text(icms_total, tag, _money(value))
    transp = etree.SubElement(inf_nfe, f"{{{NFE_NS}}}transp")
    _text(transp, "modFrete", "9")
    payment = etree.SubElement(inf_nfe, f"{{{NFE_NS}}}pag")
    payment_detail = etree.SubElement(payment, f"{{{NFE_NS}}}detPag")
    _text(payment_detail, "tPag", "99")
    _text(payment_detail, "xPag", "PAGAMENTO DE TESTE EM HOMOLOGACAO")
    _text(payment_detail, "vPag", _money(payload["total_amount"]))
    additional = etree.SubElement(inf_nfe, f"{{{NFE_NS}}}infAdic")
    _text(additional, "infCpl", "DOCUMENTO EMITIDO EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL")
    return nfe, inf_nfe, access_key


def _sign_nfe(nfe, inf_nfe, identity):
    if not isinstance(identity["private_key"], rsa.RSAPrivateKey):
        raise RuntimeError("A NF-e exige certificado com chave RSA.")
    digest = hashes.Hash(hashes.SHA1())
    digest.update(etree.tostring(inf_nfe, method="c14n", exclusive=False, with_comments=False))
    digest_value = base64.b64encode(digest.finalize()).decode("ascii")

    signature = etree.SubElement(nfe, f"{{{DS_NS}}}Signature", nsmap={"ds": DS_NS})
    signed_info = etree.SubElement(signature, f"{{{DS_NS}}}SignedInfo")
    etree.SubElement(signed_info, f"{{{DS_NS}}}CanonicalizationMethod", Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    etree.SubElement(signed_info, f"{{{DS_NS}}}SignatureMethod", Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1")
    reference = etree.SubElement(signed_info, f"{{{DS_NS}}}Reference", URI=f"#{inf_nfe.get('Id')}")
    transforms = etree.SubElement(reference, f"{{{DS_NS}}}Transforms")
    etree.SubElement(transforms, f"{{{DS_NS}}}Transform", Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature")
    etree.SubElement(transforms, f"{{{DS_NS}}}Transform", Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    etree.SubElement(reference, f"{{{DS_NS}}}DigestMethod", Algorithm="http://www.w3.org/2000/09/xmldsig#sha1")
    etree.SubElement(reference, f"{{{DS_NS}}}DigestValue").text = digest_value
    signed_bytes = etree.tostring(signed_info, method="c14n", exclusive=False, with_comments=False)
    signature_bytes = identity["private_key"].sign(
        signed_bytes,
        padding.PKCS1v15(),
        hashes.SHA1(),
    )
    etree.SubElement(signature, f"{{{DS_NS}}}SignatureValue").text = base64.b64encode(signature_bytes).decode("ascii")
    key_info = etree.SubElement(signature, f"{{{DS_NS}}}KeyInfo")
    x509_data = etree.SubElement(key_info, f"{{{DS_NS}}}X509Data")
    certificate_der = identity["certificate"].public_bytes(serialization.Encoding.DER)
    etree.SubElement(x509_data, f"{{{DS_NS}}}X509Certificate").text = base64.b64encode(certificate_der).decode("ascii")


def build_homologation_nfe(payload, *, series, number, identity=None, issued_at=None, numeric_code=None):
    identity = identity or load_fiscal_identity()
    if not identity["valid_now"]:
        raise RuntimeError("Certificado A1 vencido ou ainda nao valido; transmissao bloqueada.")
    issued_at = issued_at or datetime.now(SAO_PAULO)
    numeric_code = numeric_code if numeric_code is not None else secrets.randbelow(100_000_000)
    nfe, inf_nfe, access_key = _build_inf_nfe(
        payload, identity, series=int(series), number=int(number), issued_at=issued_at, numeric_code=numeric_code
    )
    _sign_nfe(nfe, inf_nfe, identity)
    xml = etree.tostring(nfe, encoding="utf-8", xml_declaration=True).decode("utf-8")
    schema_path = os.getenv("NANOSTORE_NFE_SCHEMA_PATH", "").strip()
    if schema_path:
        try:
            schema = etree.XMLSchema(etree.parse(str(Path(schema_path))))
            schema.assertValid(etree.fromstring(xml.encode("utf-8")))
        except (OSError, etree.XMLSchemaError, etree.DocumentInvalid) as exc:
            raise ValueError(f"XML rejeitado pelo schema oficial da NF-e: {exc}") from exc
    return {
        "access_key": access_key,
        "series": int(series),
        "number": int(number),
        "xml": xml,
        "certificate_serial": identity["serial_number"],
        "certificate_fingerprint": identity["fingerprint"],
        "issuer_cnpj": identity["cnpj"],
    }


def _authorization_envelope(signed_xml, batch_id):
    nfe = etree.fromstring(signed_xml.encode("utf-8"))
    batch = etree.Element(f"{{{NFE_NS}}}enviNFe", nsmap={None: NFE_NS}, versao="4.00")
    _text(batch, "idLote", f"{int(batch_id):015d}")
    _text(batch, "indSinc", "1")
    batch.append(nfe)
    envelope = etree.Element(f"{{{SOAP_NS}}}Envelope", nsmap={"soap12": SOAP_NS})
    body = etree.SubElement(envelope, f"{{{SOAP_NS}}}Body")
    message = etree.SubElement(body, "{http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4}nfeDadosMsg")
    message.append(batch)
    return etree.tostring(envelope, encoding="utf-8", xml_declaration=True)


def transmit_homologation_nfe(signed_xml, *, batch_id, identity=None, timeout=30):
    identity = identity or load_fiscal_identity()
    if not identity["valid_now"]:
        raise RuntimeError("Certificado A1 vencido ou ainda nao valido; transmissao bloqueada.")
    request_body = _authorization_envelope(signed_xml, batch_id)
    password = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory(prefix="nanostore-nfe-") as temp_dir:
        cert_path = Path(temp_dir) / "client.pem"
        key_path = Path(temp_dir) / "client.key"
        cert_path.write_bytes(identity["certificate"].public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(identity["private_key"].private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password.encode("ascii")),
        ))
        cert_path.chmod(0o600)
        key_path.chmod(0o600)
        context = ssl.create_default_context()
        context.load_cert_chain(cert_path, key_path, password=password)
        request = urllib.request.Request(
            AUTHORIZATION_URLS["PR"],
            data=request_body,
            headers={
                "Content-Type": f'application/soap+xml; charset=utf-8; action="{AUTHORIZATION_ACTION}"',
                "Accept": "application/soap+xml, application/xml",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, context=context, timeout=timeout) as response:
                response_xml = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"SEFAZ PR respondeu HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
            raise RuntimeError(f"Falha de comunicacao com a SEFAZ PR: {exc}") from exc

    try:
        root = etree.fromstring(response_xml.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        raise RuntimeError("Resposta da SEFAZ nao contem XML valido.") from exc
    result = root.find(f".//{{{NFE_NS}}}retEnviNFe")
    if result is None:
        raise RuntimeError("Resposta da SEFAZ sem retEnviNFe.")
    status_code = result.findtext(f"{{{NFE_NS}}}cStat", default="")
    status_reason = result.findtext(f"{{{NFE_NS}}}xMotivo", default="")
    protocol_node = result.find(f".//{{{NFE_NS}}}protNFe")
    protocol = ""
    authorized = False
    authorized_xml = ""
    if protocol_node is not None:
        protocol_status = protocol_node.findtext(f".//{{{NFE_NS}}}cStat", default=status_code)
        protocol_reason = protocol_node.findtext(f".//{{{NFE_NS}}}xMotivo", default=status_reason)
        protocol = protocol_node.findtext(f".//{{{NFE_NS}}}nProt", default="")
        status_code, status_reason = protocol_status, protocol_reason
        authorized = protocol_status == "100"
        if authorized:
            process = etree.Element(f"{{{NFE_NS}}}nfeProc", nsmap={None: NFE_NS}, versao="4.00")
            process.append(etree.fromstring(signed_xml.encode("utf-8")))
            process.append(protocol_node)
            authorized_xml = etree.tostring(process, encoding="utf-8", xml_declaration=True).decode("utf-8")
    return {
        "authorized": authorized,
        "status_code": status_code,
        "status_reason": status_reason,
        "protocol": protocol,
        "response_xml": response_xml,
        "authorized_xml": authorized_xml,
    }
