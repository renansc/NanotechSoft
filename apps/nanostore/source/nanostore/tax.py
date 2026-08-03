import re
from decimal import Decimal


MEDICINE_NCM_PREFIXES = ("3001", "3002", "3003", "3004", "3005", "3006")


def digits(value):
    return re.sub(r"\D", "", str(value or ""))


def valid_cnpj(value):
    number = digits(value)
    if len(number) != 14 or number == number[0] * 14:
        return False
    for size in (12, 13):
        base = number[:size]
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        total = sum(int(char) * weight for char, weight in zip(base, weights))
        digit = 11 - total % 11
        digit = 0 if digit >= 10 else digit
        if digit != int(number[size]):
            return False
    return True


def valid_gtin(value):
    raw = str(value or "").strip().upper()
    if raw == "SEM GTIN":
        return True
    if not raw.isdigit() or len(raw) not in {8, 12, 13, 14}:
        return False
    total = sum(int(char) * (3 if (len(raw) - index) % 2 == 0 else 1) for index, char in enumerate(raw[:-1]))
    return (10 - total % 10) % 10 == int(raw[-1])


def validate_issuer(settings, certificate_cnpj=""):
    errors = []
    cnpj = digits(settings.get("FISCAL_CNPJ"))
    required = {
        "FISCAL_LEGAL_NAME": "Razao social do emitente",
        "FISCAL_CNPJ": "CNPJ do emitente",
        "FISCAL_IE": "Inscricao estadual",
        "FISCAL_UF": "UF do emitente",
        "FISCAL_CITY_CODE": "Codigo IBGE do municipio",
        "FISCAL_CRT": "Regime tributario (CRT)",
    }
    for key, label in required.items():
        if not str(settings.get(key, "")).strip():
            errors.append(f"{label} e obrigatorio.")
    if cnpj and not valid_cnpj(cnpj):
        errors.append("CNPJ do emitente e invalido.")
    if cnpj and certificate_cnpj and cnpj != digits(certificate_cnpj):
        errors.append("CNPJ do emitente nao corresponde ao certificado digital.")
    if settings.get("FISCAL_UF", "").strip().upper() not in {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}:
        errors.append("UF do emitente e invalida.")
    if settings.get("FISCAL_CITY_CODE") and not re.fullmatch(r"\d{7}", settings["FISCAL_CITY_CODE"].strip()):
        errors.append("Codigo IBGE do municipio deve ter 7 digitos.")
    if settings.get("FISCAL_CRT") and settings["FISCAL_CRT"].strip() not in {"1", "2", "3", "4"}:
        errors.append("CRT deve ser 1, 2, 3 ou 4.")
    return errors


def validate_product(product, crt, document_model="65"):
    errors = []
    label = f"{product.sku} - {product.name}"
    if not re.fullmatch(r"\d{8}", product.ncm or ""):
        errors.append(f"{label}: NCM deve ter 8 digitos.")
    if product.cest and not re.fullmatch(r"\d{7}", product.cest):
        errors.append(f"{label}: CEST deve ter 7 digitos.")
    if not re.fullmatch(r"[567]\d{3}", product.cfop or ""):
        errors.append(f"{label}: CFOP de saida deve ter 4 digitos e iniciar por 5, 6 ou 7.")
    if (product.fiscal_origin or "") not in set("012345678"):
        errors.append(f"{label}: origem do ICMS e invalida.")
    expected_icms = 3 if str(crt) in {"1", "4"} else 2
    if not re.fullmatch(rf"\d{{{expected_icms}}}", product.icms_cst or ""):
        name = "CSOSN" if expected_icms == 3 else "CST ICMS"
        errors.append(f"{label}: {name} deve ter {expected_icms} digitos.")
    if not re.fullmatch(r"\d{2}", product.pis_cst or ""):
        errors.append(f"{label}: CST PIS deve ter 2 digitos.")
    if not re.fullmatch(r"\d{2}", product.cofins_cst or ""):
        errors.append(f"{label}: CST COFINS deve ter 2 digitos.")
    if not str(product.tax_unit or "").strip():
        errors.append(f"{label}: unidade tributavel e obrigatoria.")
    if not valid_gtin(product.gtin_taxable):
        errors.append(f"{label}: GTIN tributavel e invalido; informe um GTIN valido ou SEM GTIN.")
    if product.has_tax_benefit and not re.fullmatch(r"[A-Z0-9]{8,10}", (product.benefit_code or "").upper()):
        errors.append(f"{label}: codigo de beneficio fiscal e obrigatorio para item beneficiado.")
    if document_model == "55" and (product.ncm or "").startswith(MEDICINE_NCM_PREFIXES):
        if not (re.fullmatch(r"\d{13}", product.anvisa_code or "") or (product.anvisa_code or "").upper() == "ISENTO"):
            errors.append(f"{label}: codigo ANVISA de 13 digitos ou ISENTO e obrigatorio na NF-e.")
        if Decimal(product.max_consumer_price or 0) <= 0:
            errors.append(f"{label}: preco maximo ao consumidor deve ser maior que zero na NF-e.")
    if str(crt) == "3":
        if not re.fullmatch(r"\d{3}", product.ibs_cbs_cst or ""):
            errors.append(f"{label}: CST IBS/CBS deve ter 3 digitos.")
        if not re.fullmatch(r"\d{6}", product.tax_classification or ""):
            errors.append(f"{label}: cClassTrib deve ter 6 digitos.")
        elif not product.tax_classification.startswith(product.ibs_cbs_cst or "x"):
            errors.append(f"{label}: cClassTrib deve iniciar pelo CST IBS/CBS.")
        for field, name in (("ibs_uf_rate", "IBS UF"), ("ibs_mun_rate", "IBS municipal"), ("cbs_rate", "CBS")):
            if Decimal(getattr(product, field, 0) or 0) < 0:
                errors.append(f"{label}: aliquota {name} nao pode ser negativa.")
    return errors
