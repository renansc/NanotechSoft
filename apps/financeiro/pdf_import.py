import hashlib
import re
import shutil
import subprocess
import tempfile
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


MAX_PDF_PAGES = 10
MAX_INSTALLMENT_PAGES = 60


class FinancePdfImportError(ValueError):
    pass


def _fold(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in normalized if not unicodedata.combining(char)).upper()


def _brl_decimal(value):
    try:
        return Decimal(str(value).replace(".", "").replace(",", "."))
    except InvalidOperation as exc:
        raise FinancePdfImportError(f"Valor bancário inválido: {value}") from exc


def _caixa_fitid(account, date, time_value, document, amount, memo):
    identity = "|".join((
        "CAIXA",
        account,
        date,
        time_value,
        document,
        format(amount, ".2f"),
        _fold(memo),
    ))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"pdf-caixa-{digest}"


def _inter_fitid(account, date, amount, memo, occurrence):
    identity = "|".join((
        "BANCO INTER",
        account,
        date,
        format(amount, ".2f"),
        _fold(memo),
        str(occurrence),
    ))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"pdf-inter-{digest}"


def _parse_inter_long_date(day, month_name, year):
    months = {
        "JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4,
        "MAIO": 5, "JUNHO": 6, "JULHO": 7, "AGOSTO": 8,
        "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12,
    }
    month = months.get(_fold(month_name))
    if not month:
        return ""
    try:
        return datetime(int(year), month, int(day)).date().isoformat()
    except ValueError:
        return ""


def parse_inter_statement_text(text):
    folded = _fold(text)
    if "INSTITUICAO: BANCO INTER" not in folded:
        raise FinancePdfImportError("O PDF não corresponde ao modelo de extrato do Banco Inter.")

    account_match = re.search(r"(?i)Conta:\s*([0-9.\-]+)", text)
    period_match = re.search(
        r"(?i)Per[ií]odo:\s*(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})",
        text,
    )
    total_match = re.search(
        r"(?is)Saldo\s+total.*?R\$\s*([\d.]+,\d{2})",
        text,
    )
    account = account_match.group(1) if account_match else ""
    closing_balance = float(_brl_decimal(total_match.group(1))) if total_match else None
    current_date = ""
    balance_date = ""
    daily_balance = None
    occurrences = {}
    transactions = []
    date_head = re.compile(
        r"(?i)^\s*(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)\s+de\s+(\d{4})\s+Saldo\s+do\s+dia:\s*R\$\s*([\d.]+,\d{2})"
    )
    transaction_line = re.compile(
        r'^\s*(.+?)\s+(-?R\$\s*[\d.]+,\d{2})\s+(-?R\$\s*[\d.]+,\d{2})\s*$'
    )

    for raw_line in str(text or "").splitlines():
        head = date_head.match(raw_line)
        if head:
            current_date = _parse_inter_long_date(head.group(1), head.group(2), head.group(3))
            if current_date and (not balance_date or current_date >= balance_date):
                balance_date = current_date
                daily_balance = float(_brl_decimal(head.group(4)))
            continue
        if not current_date:
            continue
        transaction = transaction_line.match(raw_line)
        if not transaction:
            continue
        memo, amount_text, transaction_balance_text = transaction.groups()
        amount_is_negative = amount_text.strip().startswith("-")
        amount = _brl_decimal(amount_text.replace("R$", "").replace("-", "").strip())
        if amount_is_negative:
            amount = -amount
        balance_is_negative = transaction_balance_text.strip().startswith("-")
        transaction_balance = _brl_decimal(
            transaction_balance_text.replace("R$", "").replace("-", "").strip()
        )
        if balance_is_negative:
            transaction_balance = -transaction_balance
        normalized_memo = " ".join(memo.split()).strip()
        identity = (current_date, format(amount, ".2f"), _fold(normalized_memo))
        occurrences[identity] = occurrences.get(identity, 0) + 1
        transactions.append({
            "date": current_date,
            "amount": float(amount),
            "fitid": _inter_fitid(
                account,
                current_date,
                amount,
                normalized_memo,
                occurrences[identity],
            ),
            "memo": normalized_memo,
            "trntype": "CREDIT" if amount >= 0 else "DEBIT",
            "transactionBalance": float(transaction_balance),
        })

    if not transactions:
        raise FinancePdfImportError("Nenhuma transação foi reconhecida no extrato do Banco Inter.")
    if closing_balance is None:
        closing_balance = daily_balance

    return {
        "bank": "BANCO INTER",
        "account": account,
        "periodStart": datetime.strptime(period_match.group(1), "%d/%m/%Y").date().isoformat()
        if period_match else "",
        "periodEnd": datetime.strptime(period_match.group(2), "%d/%m/%Y").date().isoformat()
        if period_match else "",
        "closingBalance": closing_balance,
        "balanceDate": balance_date,
        "txs": transactions,
    }


def parse_caixa_statement_text(text):
    folded = _fold(text)
    if "EXTRATO POR PERIODO" not in folded and "ALO CAIXA" not in folded:
        raise FinancePdfImportError("O PDF não corresponde ao modelo de extrato da Caixa.")

    account_match = re.search(r"(?im)^\s*Conta\s+(.+?)\s*$", text)
    period_match = re.search(
        r"(?i)Per[ií]odo\s+dos\s+lan[cç]amentos\s+(\d{2}/\d{2}/\d{4})\s+at[eé]\s+(\d{2}/\d{2}/\d{4})",
        text,
    )
    account = " ".join(account_match.group(1).split()) if account_match else ""

    transaction_head = re.compile(
        r"^\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}:\d{2}:\d{2})\s+(\d{6})\s+(.+?)\s*$"
    )
    money_token = re.compile(r"(?<!\d)(\d+(?:\.\d{3})*,\d{2})\s*([CD])(?=\s|$)", re.I)
    transactions = []
    closing_balance = None
    balance_date = ""

    for raw_line in str(text or "").splitlines():
        line = " ".join(raw_line.replace("€", "C").replace("|", " ").split())
        head = transaction_head.match(line)
        if not head:
            continue

        date_br, time_value, document, remainder = head.groups()
        values = list(money_token.finditer(remainder))
        if not values:
            continue

        try:
            date_iso = datetime.strptime(date_br, "%d/%m/%Y").date().isoformat()
        except ValueError:
            continue

        if "SALDO DIA" in _fold(remainder):
            balance_match = values[-1]
            balance = _brl_decimal(balance_match.group(1))
            if balance_match.group(2).upper() == "D":
                balance = -balance
            if not balance_date or date_iso >= balance_date:
                balance_date = date_iso
                closing_balance = float(balance)
            continue

        value_match = values[0]
        memo = remainder[:value_match.start()].strip(" -—")
        if not memo:
            continue

        amount = _brl_decimal(value_match.group(1))
        direction = value_match.group(2).upper()
        if direction == "D":
            amount = -amount

        transactions.append({
            "date": date_iso,
            "amount": float(amount),
            "fitid": _caixa_fitid(
                account,
                date_iso,
                time_value,
                document,
                amount,
                memo,
            ),
            "memo": memo,
            "trntype": "CREDIT" if amount >= 0 else "DEBIT",
            "document": document,
            "time": time_value,
        })

    if not transactions:
        raise FinancePdfImportError("Nenhuma transação foi reconhecida no extrato da Caixa.")

    return {
        "bank": "CAIXA",
        "account": account,
        "periodStart": datetime.strptime(period_match.group(1), "%d/%m/%Y").date().isoformat()
        if period_match else "",
        "periodEnd": datetime.strptime(period_match.group(2), "%d/%m/%Y").date().isoformat()
        if period_match else "",
        "closingBalance": closing_balance,
        "balanceDate": balance_date,
        "txs": transactions,
    }


def parse_bank_statement_text(text):
    folded = _fold(text)
    if "EXTRATO POR PERIODO" in folded or "ALO CAIXA" in folded:
        return parse_caixa_statement_text(text)
    if "INSTITUICAO: BANCO INTER" in folded:
        return parse_inter_statement_text(text)
    raise FinancePdfImportError(
        "Modelo de PDF ainda não suportado. Atualmente estão disponíveis: Caixa e Banco Inter."
    )


def _run(command, timeout):
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        ).stdout
    except FileNotFoundError as exc:
        raise FinancePdfImportError("O servidor não possui as ferramentas de leitura de PDF.") from exc
    except subprocess.TimeoutExpired as exc:
        raise FinancePdfImportError("O PDF demorou demais para ser processado.") from exc
    except subprocess.CalledProcessError as exc:
        raise FinancePdfImportError("Não foi possível processar o conteúdo do PDF.") from exc


def extract_bank_statement_pdf(pdf_path):
    pdf_path = Path(pdf_path)
    for executable in ("pdfinfo", "pdftotext", "pdftoppm", "tesseract"):
        if not shutil.which(executable):
            raise FinancePdfImportError("O servidor não possui as ferramentas de leitura de PDF.")

    info = _run(["pdfinfo", str(pdf_path)], timeout=20)
    pages_match = re.search(r"(?im)^Pages:\s+(\d+)\s*$", info)
    page_count = int(pages_match.group(1)) if pages_match else 0
    if not page_count or page_count > MAX_PDF_PAGES:
        raise FinancePdfImportError(f"O PDF deve conter entre 1 e {MAX_PDF_PAGES} páginas.")

    searchable_text = _run(["pdftotext", "-layout", str(pdf_path), "-"], timeout=30)
    try:
        return parse_bank_statement_text(searchable_text)
    except FinancePdfImportError:
        pass

    with tempfile.TemporaryDirectory(prefix="financeiro-pdf-") as temp_dir:
        output_prefix = str(Path(temp_dir) / "page")
        _run(
            [
                "pdftoppm",
                "-f", "1",
                "-l", str(page_count),
                "-r", "220",
                "-png",
                str(pdf_path),
                output_prefix,
            ],
            timeout=90,
        )
        page_texts = []
        for page_path in sorted(Path(temp_dir).glob("page-*.png")):
            page_texts.append(_run(
                ["tesseract", str(page_path), "stdout", "-l", "por", "--psm", "6"],
                timeout=60,
            ))

    return parse_bank_statement_text("\n".join(page_texts))


def _first_iso_date(text):
    payment_deadline = re.search(
        r"(?is)pagar\s+(?:este\s+documento\s+)?at[eé]\s*:\s*(\d{2}/\d{2}/\d{4})",
        text,
    )
    labelled = re.search(
        r"(?is)(?:vencimento|data\s+de\s+vencimento|vence\s+em)\D{0,35}(\d{2}/\d{2}/\d{4})",
        text,
    )
    if payment_deadline:
        candidates = [payment_deadline.group(1)]
    elif labelled:
        candidates = [labelled.group(1)]
    else:
        candidates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", text)
    for value in candidates:
        try:
            return datetime.strptime(value, "%d/%m/%Y").date().isoformat()
        except ValueError:
            continue
    return ""


def _installment_amount(text):
    patterns = (
        r"(?is)\bValor\s*:\s*(\d{1,3}(?:\.\d{3})*,\d{2})",
        r"(?is)Valor\s+Total\s+do\s+Documento.{0,250}?(\d{1,3}(?:\.\d{3})*,\d{2})",
        r"(?is)Valor\s+do\s+Documento[^\n]*\n\s*(\d{1,3}(?:\.\d{3})*,\d{2})",
        r"(?is)(?:valor\s+(?:do\s+)?documento|valor\s+(?:da\s+)?parcela|valor\s+cobrado)\D{0,35}(\d{1,3}(?:\.\d{3})*,\d{2})",
        r"(?is)R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(_brl_decimal(match.group(1)))
    return None


def _installment_barcode(text):
    boleto_line = re.search(
        r"\b\d{3}-\d\s+(\d{5}\.\d{5})\s+(\d{5}\.\d{6})\s+"
        r"(\d{5}\.\d{6})\s+(\d)\s+(\d{14})\b",
        text,
    )
    if boleto_line:
        return "".join(re.sub(r"\D", "", group) for group in boleto_line.groups())
    for line in str(text or "").splitlines():
        digits = re.sub(r"\D", "", line)
        if len(digits) in {44, 46, 47, 48}:
            return digits
    compact = re.sub(r"\D", "", text)
    match = re.search(r"\d{47,48}", compact)
    return match.group(0) if match else ""


def _installment_pix(text):
    compact = re.sub(r"\s+", "", str(text or ""))
    match = re.search(r"000201[0-9A-Za-z.\-_/]{40,900}?6304[0-9A-Fa-f]{4}", compact)
    return match.group(0) if match else ""


def _installment_segments(text):
    header = re.compile(
        r"\b\d{3}-\d\s+\d{5}\.\d{5}\s+\d{5}\.\d{6}\s+"
        r"\d{5}\.\d{6}\s+\d\s+\d{14}\b"
    )
    matches = list(header.finditer(str(text or "")))
    if not matches:
        return [str(text or "")]
    return [
        str(text or "")[match.start(): matches[index + 1].start() if index + 1 < len(matches) else None]
        for index, match in enumerate(matches)
    ]


def parse_installment_pages(page_texts):
    pages = []
    total = len(page_texts)
    for index, text in enumerate(page_texts, start=1):
        segments = _installment_segments(text)
        for region_index, segment in enumerate(segments, start=1):
            installment_match = re.search(
                r"(?is)Parcela\s+Vencimento.*?\n\s*(\d{1,3})\s*/\s*(\d{1,3})\s+(\d{2}/\d{2}/\d{4})",
                segment,
            )
            due_date = _first_iso_date(segment)
            installment_number = None
            installment_total = None
            if installment_match:
                installment_number = int(installment_match.group(1))
                installment_total = int(installment_match.group(2))
                try:
                    due_date = datetime.strptime(installment_match.group(3), "%d/%m/%Y").date().isoformat()
                except ValueError:
                    pass
            amount = _installment_amount(segment)
            barcode = _installment_barcode(segment)
            pix = _installment_pix(segment)
            issues = []
            if not due_date:
                issues.append("Vencimento não reconhecido")
            if amount is None:
                issues.append("Valor não reconhecido")
            pages.append({
                "page": index,
                "pageCount": total,
                "region": region_index,
                "regionsOnPage": len(segments),
                "installmentNumber": installment_number,
                "installmentTotal": installment_total,
                "dueDate": due_date,
                "amount": amount,
                "barcode": barcode,
                "pix": pix,
                "textPreview": " ".join(segment.split())[:300],
                "issues": issues,
            })
    return pages


def extract_installment_pdf(pdf_path):
    pdf_path = Path(pdf_path)
    for executable in ("pdfinfo", "pdftotext", "pdftoppm", "tesseract"):
        if not shutil.which(executable):
            raise FinancePdfImportError("O servidor não possui as ferramentas de leitura de PDF.")

    info = _run(["pdfinfo", str(pdf_path)], timeout=20)
    pages_match = re.search(r"(?im)^Pages:\s+(\d+)\s*$", info)
    page_count = int(pages_match.group(1)) if pages_match else 0
    if not page_count or page_count > MAX_INSTALLMENT_PAGES:
        raise FinancePdfImportError(
            f"O PDF parcelado deve conter entre 1 e {MAX_INSTALLMENT_PAGES} páginas."
        )

    page_texts = []
    with tempfile.TemporaryDirectory(prefix="financeiro-parcelas-") as temp_dir:
        temp_path = Path(temp_dir)
        for page in range(1, page_count + 1):
            text = _run(
                ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdf_path), "-"],
                timeout=20,
            )
            if len(text.strip()) < 30:
                prefix = temp_path / f"page-{page}"
                _run(
                    ["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-r", "220", "-png", str(pdf_path), str(prefix)],
                    timeout=45,
                )
                text = _run(
                    ["tesseract", str(prefix) + ".png", "stdout", "-l", "por", "--psm", "6"],
                    timeout=60,
                )
            page_texts.append(text)

    return {"pageCount": page_count, "pages": parse_installment_pages(page_texts)}


def extract_installment_pdf_page(pdf_path, page):
    pdf_path = Path(pdf_path)
    page = int(page)
    if page < 1 or page > MAX_INSTALLMENT_PAGES:
        raise FinancePdfImportError("Página do PDF inválida.")
    text = _run(
        ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdf_path), "-"],
        timeout=20,
    )
    return parse_installment_pages([text])
