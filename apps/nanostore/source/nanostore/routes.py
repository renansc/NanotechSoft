from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import os
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from flask import Blueprint, Response, abort, jsonify, render_template, request, send_file
from sqlalchemy import and_, case, func, or_
from zoneinfo import ZoneInfo
from werkzeug.exceptions import HTTPException

from .extensions import db
from .documents import build_fiscal_pdf, build_order_pdf
from .fiscal import build_signed_simulation, fiscal_certificate_status, load_fiscal_identity
from .tax import icms_code_profile, valid_gtin, validate_issuer, validate_product
from .store_modes import STORE_MODES, resolve_store_mode
from .models import (
    CashMovement,
    CashSession,
    DistributionTable,
    FiscalSimulation,
    IntegrationSetting,
    InventoryCount,
    InventoryCountItem,
    FinancialEntry,
    InternalChatMessage,
    PharmacyCategory,
    PharmacyCustomer,
    PharmacyLot,
    PharmacyPayment,
    PharmacyProduct,
    PharmacySale,
    PharmacySaleItem,
    PharmacySupplier,
    PurchaseOrder,
    PurchaseOrderItem,
    StockMovement,
    WorkflowStage,
    WorkflowTicket,
)

bp = Blueprint("main", __name__)


def _certs_dir():
    return os.environ.get("APP_CERT_DIR", "/app/certs")


def _split_csv_env(value):
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _https_runtime_config():
    server_name = (os.environ.get("SERVER_NAME") or "_").strip()
    cert_hosts = _split_csv_env(os.environ.get("CERT_APP_HOSTS"))
    public_base_url = (os.environ.get("PUBLIC_BASE_URL") or "").strip()
    if public_base_url:
        parsed_public_url = urlparse(public_base_url)
        cert_hosts.append(parsed_public_url.hostname or public_base_url)
    if server_name and server_name != "_":
        cert_hosts.append(server_name)
    cert_hosts.extend(["127.0.0.1", "localhost"])
    unique_hosts = []
    seen = set()
    for host in cert_hosts:
        if host not in seen:
            seen.add(host)
            unique_hosts.append(host)
    return {
        "enabled": str(os.environ.get("ENABLE_HTTPS", "1")).strip().lower() not in {"0", "false", "off", "no"},
        "server_name": server_name,
        "public_base_url": public_base_url,
        "cert_hosts": unique_hosts,
        "http_port": str(os.environ.get("HTTP_PORT", "8080")).strip() or "8080",
        "https_port": str(os.environ.get("HTTPS_PORT", "8443")).strip() or "8443",
    }


def _normalize_host(host_value):
    raw = (host_value or "").strip()
    if not raw:
        return ""
    if raw.startswith("[") and "]" in raw:
        return raw[1:raw.index("]")]
    return raw.split(":", 1)[0]


def _cert_path(name):
    configured_paths = {
        "nanostore-ca.crt": os.environ.get("APP_CA_CERT_PATH"),
        "nanostore-app.crt": os.environ.get("APP_HTTPS_CERT_PATH"),
    }
    configured = (configured_paths.get(name) or "").strip()
    if configured:
        return configured
    return os.path.join(_certs_dir(), name)


def _load_pem_certificate(path, label):
    if not os.path.exists(path):
        raise RuntimeError(f"Certificado {label} nao encontrado em {path}.")
    with open(path, "rb") as f:
        pem_bytes = f.read()
    cert = x509.load_pem_x509_certificate(pem_bytes)
    der_bytes = cert.public_bytes(serialization.Encoding.DER)
    return pem_bytes, der_bytes


@bp.app_errorhandler(HTTPException)
def handle_http_exception(exc):
    return jsonify({"ok": False, "error": exc.description}), exc.code


@bp.app_errorhandler(Exception)
def handle_unexpected_exception(exc):
    return jsonify({"ok": False, "error": str(exc)}), 500


@bp.after_app_request
def apply_security_headers(response):
    response.headers.setdefault("Permissions-Policy", "camera=(self)")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


def _to_decimal(value, field_name, default="0"):
    raw = default if value in {None, ""} else str(value).strip().replace(",", ".")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Valor invalido para {field_name}.") from exc


def _parse_date(value, field_name):
    raw = (value or "").strip()
    if not raw:
        raise ValueError(f"{field_name} obrigatoria.")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} invalida.") from exc


def _to_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on", "sim"}


def _setting_map():
    return {row.key: row.value for row in IntegrationSetting.query.order_by(IntegrationSetting.key.asc()).all()}


def _set_setting(key, value):
    row = IntegrationSetting.query.filter_by(key=key).first() or IntegrationSetting(key=key, value="")
    row.value = "" if value is None else str(value).strip()
    db.session.add(row)


def _product_stock(product_id):
    stock = db.session.query(func.coalesce(func.sum(PharmacyLot.quantity_available), 0)).filter_by(product_id=product_id).scalar()
    return Decimal(stock or 0)


def _log_stock_movement(*, movement_type, product, lot, quantity, reference_code="", notes=""):
    db.session.add(
        StockMovement(
            movement_type=movement_type,
            product_id=product.id,
            lot_id=lot.id if lot else None,
            quantity=quantity,
            balance_after=Decimal(lot.quantity_available or 0) if lot else Decimal("0"),
            reference_code=reference_code,
            notes=notes,
        )
    )


def _serialize_product(product):
    category = product.category
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "barcode": product.barcode or "",
        "brand": product.brand or "",
        "active_ingredient": product.active_ingredient or "",
        "unit": product.unit or "un",
        "category_name": product.category.name if product.category else "",
        "category_id": product.category_id,
        "supplier_name": product.supplier.name if product.supplier else "",
        "supplier_id": product.supplier_id,
        "stock": float(_product_stock(product.id)),
        "minimum_stock": float(product.minimum_stock or 0),
        "sale_price": float(product.sale_price or 0),
        "cost_price": float(product.cost_price or 0),
        "tracks_inventory": product.tracks_inventory,
        "requires_prescription": product.requires_prescription,
        "is_controlled": product.is_controlled,
        "is_active": product.is_active,
        "minimum_profit_margin": float(category.minimum_profit_margin or 0) if category else 0.0,
        "suggested_profit_margin": float(category.suggested_profit_margin or 0) if category else 0.0,
        "ncm": product.ncm, "cest": product.cest, "cfop": product.cfop,
        "fiscal_origin": product.fiscal_origin, "icms_cst": product.icms_cst,
        "pis_cst": product.pis_cst, "cofins_cst": product.cofins_cst,
        "tax_unit": product.tax_unit, "gtin_taxable": product.gtin_taxable,
        "benefit_code": product.benefit_code, "has_tax_benefit": product.has_tax_benefit,
        "anvisa_code": product.anvisa_code,
        "max_consumer_price": float(product.max_consumer_price or 0),
        "ibs_cbs_cst": product.ibs_cbs_cst, "tax_classification": product.tax_classification,
        "ibs_uf_rate": float(product.ibs_uf_rate or 0), "ibs_mun_rate": float(product.ibs_mun_rate or 0),
        "cbs_rate": float(product.cbs_rate or 0),
    }


def _serialize_lot(lot):
    return {
        "id": lot.id,
        "product_id": lot.product_id,
        "product_sku": lot.product.sku if lot.product else "",
        "product_name": lot.product.name if lot.product else "",
        "barcode": lot.product.barcode if lot.product else "",
        "lot_code": lot.lot_code,
        "expiration_date": lot.expiration_date.isoformat(),
        "quantity_received": float(lot.quantity_received or 0),
        "quantity_available": float(lot.quantity_available or 0),
        "purchase_price": float(lot.purchase_price or 0),
        "stock_cost": float(Decimal(lot.quantity_available or 0) * Decimal(lot.purchase_price or 0)),
        "location": lot.location,
    }


def _serialize_stock_movement(movement):
    return {
        "id": movement.id,
        "movement_type": movement.movement_type,
        "product_name": movement.product.name if movement.product else "",
        "lot_code": movement.lot.lot_code if movement.lot else "",
        "quantity": float(movement.quantity or 0),
        "balance_after": float(movement.balance_after or 0),
        "reference_code": movement.reference_code,
        "notes": movement.notes,
        "created_at": movement.created_at.isoformat() + "Z",
    }


def _serialize_sale(sale):
    paid_amount = _sale_paid_amount(sale.id)
    balance_amount = max(Decimal(sale.total_amount or 0) - paid_amount, Decimal("0"))
    table_id = next(
        (table.id for table in DistributionTable.query.filter_by(is_active=True).all()
         if table.reference == sale.table_reference),
        None,
    ) if sale.fulfillment_type == "table" else None
    return {
        "id": sale.id,
        "code": sale.code,
        "customer_name": sale.customer_name,
        "source_channel": sale.source_channel,
        "status": sale.status,
        "total_amount": float(sale.total_amount or 0),
        "paid_amount": float(paid_amount),
        "balance_amount": float(balance_amount),
        "fulfillment_type": sale.fulfillment_type,
        "table_reference": sale.table_reference,
        "table_id": table_id,
        "delivery_address": sale.delivery_address,
        "delivery_status": sale.delivery_status,
        "completed_at": sale.completed_at.isoformat() + "Z" if sale.completed_at else "",
        "customer_id": sale.customer_id,
        "customer_phone": sale.customer_phone,
        "notes": sale.notes,
        "external_order_id": sale.external_order_id,
        "created_at": sale.created_at.isoformat() + "Z",
        "subtotal_amount": float(sale.subtotal_amount or 0),
        "discount_amount": float(sale.discount_amount or 0),
        "items": [
            {
                "product_id": item.product_id,
                "sku": item.product.sku if item.product else "",
                "product_name": item.product.name if item.product else "",
                "lot_code": item.lot.lot_code if item.lot else "",
                "quantity": float(item.quantity or 0),
                "unit_price": float(item.unit_price or 0),
                "discount_amount": float(item.discount_amount or 0),
                "total_amount": float(item.total_amount or 0),
            }
            for item in sale.items.order_by(PharmacySaleItem.id.asc()).all()
        ],
    }


def _serialize_sale_report(sale):
    return {
        "id": sale.id,
        "code": sale.code,
        "customer_name": sale.customer_name,
        "status": sale.status,
        "total_amount": float(sale.total_amount or 0),
        "fulfillment_type": sale.fulfillment_type,
        "table_reference": sale.table_reference,
        "delivery_address": sale.delivery_address,
        "delivery_status": sale.delivery_status,
        "created_at": sale.created_at.isoformat() + "Z",
    }


def _sale_fiscal_payload(sale):
    settings = _setting_map()
    return {
        "code": sale.code,
        "customer_name": sale.customer_name,
        "source_channel": sale.source_channel,
        "subtotal_amount": sale.subtotal_amount,
        "discount_amount": sale.discount_amount,
        "total_amount": sale.total_amount,
        "issuer": {key: settings.get(key, "") for key in (
            "FISCAL_LEGAL_NAME", "FISCAL_CNPJ", "FISCAL_IE", "FISCAL_UF", "FISCAL_CITY_CODE", "FISCAL_CRT"
        )},
        "items": [
            {
                "sku": item.product.sku if item.product else "",
                "product_name": item.product.name if item.product else "",
                "lot_code": item.lot.lot_code if item.lot else "",
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "discount_amount": item.discount_amount,
                "total_amount": item.total_amount,
                "ncm": item.product.ncm, "cest": item.product.cest, "cfop": item.product.cfop,
                "origin": item.product.fiscal_origin, "icms_cst": item.product.icms_cst,
                "pis_cst": item.product.pis_cst, "cofins_cst": item.product.cofins_cst,
                "tax_unit": item.product.tax_unit, "gtin_taxable": item.product.gtin_taxable,
                "benefit_code": item.product.benefit_code, "anvisa_code": item.product.anvisa_code,
                "max_consumer_price": item.product.max_consumer_price,
                "ibs_cbs_cst": item.product.ibs_cbs_cst, "tax_classification": item.product.tax_classification,
                "ibs_uf_rate": item.product.ibs_uf_rate, "ibs_mun_rate": item.product.ibs_mun_rate,
                "cbs_rate": item.product.cbs_rate,
            }
            for item in sale.items.order_by(PharmacySaleItem.id.asc()).all()
        ],
    }


def _serialize_fiscal_simulation(simulation):
    return {
        "id": simulation.id,
        "code": simulation.code,
        "sale_id": simulation.sale_id,
        "sale_code": simulation.sale.code if simulation.sale else "",
        "document_model": simulation.document_model,
        "environment": simulation.environment,
        "status": simulation.status,
        "issuer_cnpj": simulation.issuer_cnpj,
        "total_amount": float(simulation.total_amount or 0),
        "created_at": simulation.created_at.isoformat() + "Z",
        "xml_url": f"/api/fiscal/simulations/{simulation.id}/xml",
        "pdf_url": f"/api/fiscal/simulations/{simulation.id}/pdf",
    }


def _serialize_purchase(purchase):
    return {
        "id": purchase.id,
        "code": purchase.code,
        "supplier_name": purchase.supplier.name if purchase.supplier else "",
        "purchase_type": purchase.purchase_type,
        "status": purchase.status,
        "order_date": purchase.order_date.isoformat(),
        "expected_date": purchase.expected_date.isoformat() if purchase.expected_date else "",
        "total_amount": float(purchase.total_amount or 0),
    }


def _serialize_financial_entry(entry):
    return {
        "id": entry.id,
        "entry_type": entry.entry_type,
        "category": entry.category,
        "description": entry.description,
        "counterparty": entry.counterparty,
        "amount": float(entry.amount or 0),
        "status": entry.status,
        "due_date": entry.due_date.isoformat(),
        "source_ref": entry.source_ref,
    }


def _serialize_payment(payment):
    return {
        "id": payment.id,
        "sale_code": payment.sale.code if payment.sale else "",
        "cash_session_id": payment.cash_session_id,
        "method": payment.method,
        "provider": payment.provider,
        "amount": float(payment.amount or 0),
        "status": payment.status,
        "transaction_reference": payment.transaction_reference,
        "pix_qr_code": payment.pix_qr_code,
        "pix_copy_paste": payment.pix_copy_paste,
        "paid_at": payment.paid_at.isoformat() + "Z" if payment.paid_at else "",
    }


def _serialize_customer(customer):
    address = ", ".join(part for part in (
        customer.address, customer.address_number, customer.neighborhood, customer.city, customer.state, customer.postal_code
    ) if part)
    return {
        "id": customer.id, "name": customer.name, "document": customer.document,
        "phone": customer.phone, "address": customer.address, "address_number": customer.address_number,
        "neighborhood": customer.neighborhood, "city": customer.city, "state": customer.state,
        "postal_code": customer.postal_code, "full_address": address, "notes": customer.notes,
        "created_at": customer.created_at.isoformat() + "Z",
    }


def _serialize_cash_movement(movement):
    return {
        "id": movement.id, "cash_session_id": movement.cash_session_id, "direction": movement.direction,
        "category": movement.category, "description": movement.description, "amount": float(movement.amount or 0),
        "created_at": movement.created_at.isoformat() + "Z",
    }


def _cash_report():
    rows = []
    sessions = CashSession.query.order_by(CashSession.opened_at.desc(), CashSession.id.desc()).all()
    for session in sessions:
        opening_amount = Decimal(session.opening_amount or 0)
        if opening_amount > 0:
            rows.append({
                "cash_session_id": session.id,
                "origin": "Abertura",
                "direction": "in",
                "category": "Saldo inicial",
                "description": f"Abertura do caixa #{session.id}",
                "amount": float(opening_amount),
                "occurred_at": session.opened_at.isoformat() + "Z",
            })

    for movement in CashMovement.query.order_by(CashMovement.created_at.desc(), CashMovement.id.desc()).all():
        rows.append({
            "cash_session_id": movement.cash_session_id,
            "origin": "Movimento manual",
            "direction": movement.direction,
            "category": movement.category or "Sem categoria",
            "description": movement.description,
            "amount": float(movement.amount or 0),
            "occurred_at": movement.created_at.isoformat() + "Z",
        })

    payments = PharmacyPayment.query.filter(
        PharmacyPayment.status.in_(["paid", "authorized"]),
        PharmacyPayment.cash_session_id.isnot(None),
    ).order_by(PharmacyPayment.created_at.desc(), PharmacyPayment.id.desc()).all()
    for payment in payments:
        rows.append({
            "cash_session_id": payment.cash_session_id,
            "origin": "Recebimento",
            "direction": "in",
            "category": payment.method or "Pagamento",
            "description": payment.sale.code if payment.sale else payment.transaction_reference,
            "amount": float(payment.amount or 0),
            "occurred_at": (payment.paid_at or payment.created_at).isoformat() + "Z",
        })

    rows.sort(key=lambda item: item["occurred_at"], reverse=True)
    entries = sum(Decimal(str(item["amount"])) for item in rows if item["direction"] == "in")
    exits = sum(Decimal(str(item["amount"])) for item in rows if item["direction"] == "out")
    return {
        "rows": rows,
        "entries": [item for item in rows if item["direction"] == "in"],
        "exits": [item for item in rows if item["direction"] == "out"],
        "entries_total": float(entries),
        "exits_total": float(exits),
        "balance": float(entries - exits),
    }


def _serialize_inventory_count(count):
    return {
        "id": count.id,
        "code": count.code,
        "status": count.status,
        "count_date": count.count_date.isoformat(),
        "items": [
            {
                "product_name": item.product.name if item.product else "",
                "lot_code": item.lot.lot_code if item.lot else "",
                "expected_quantity": float(item.expected_quantity or 0),
                "counted_quantity": float(item.counted_quantity or 0),
                "difference_quantity": float(item.difference_quantity or 0),
            }
            for item in count.items.order_by(InventoryCountItem.id.asc()).all()
        ],
    }


def _default_stage():
    return WorkflowStage.query.filter_by(is_default=True).first() or WorkflowStage.query.order_by(WorkflowStage.order_index.asc(), WorkflowStage.id.asc()).first()


def _serialize_ticket_message(message):
    return {
        "id": message.id,
        "author_name": message.author_name,
        "message": message.message,
        "created_at": message.created_at.isoformat() + "Z",
    }


def _serialize_ticket(ticket):
    return {
        "id": ticket.id,
        "code": ticket.code,
        "title": ticket.title,
        "customer_name": ticket.customer_name,
        "customer_phone": ticket.customer_phone,
        "source_channel": ticket.source_channel,
        "priority": ticket.priority,
        "status": ticket.status,
        "stage_id": ticket.stage_id,
        "stage_name": ticket.stage.name if ticket.stage else "",
        "stage_color": ticket.stage.color if ticket.stage else "#2d8a4d",
        "sale_code": ticket.sale.code if ticket.sale else "",
        "assigned_to": ticket.assigned_to,
        "description": ticket.description,
        "messages": [_serialize_ticket_message(msg) for msg in ticket.messages.order_by(InternalChatMessage.created_at.asc()).all()],
    }


def _serialize_workflow_stage(stage):
    return {
        "id": stage.id,
        "name": stage.name,
        "color": stage.color,
        "order_index": stage.order_index,
        "is_default": stage.is_default,
        "is_closed": stage.is_closed,
    }


def _serialize_category(category):
    return {
        "id": category.id,
        "name": category.name,
        "description": category.description or "",
        "minimum_profit_margin": float(category.minimum_profit_margin or 0),
        "suggested_profit_margin": float(category.suggested_profit_margin or 0),
    }


def _margin_floor_price(cost_price, category):
    margin_percent = Decimal(category.minimum_profit_margin or 0) if category else Decimal("0")
    return (Decimal(cost_price or 0) * (Decimal("1") + (margin_percent / Decimal("100")))).quantize(Decimal("0.01"))


def _ensure_workflow_ticket_for_sale(sale):
    if sale.source_channel != "whatsapp":
        return None
    existing = WorkflowTicket.query.filter_by(sale_id=sale.id).first()
    if existing:
        return existing
    stage = _default_stage()
    if not stage:
        return None
    ticket = WorkflowTicket(
        code=f"WK-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid4().hex[:5].upper()}",
        title=f"Venda WhatsApp {sale.code}",
        customer_name=sale.customer_name,
        customer_phone=sale.customer_phone,
        source_channel=sale.source_channel,
        priority="normal",
        status="open",
        stage_id=stage.id,
        sale_id=sale.id,
        description=sale.notes or "Card criado automaticamente a partir de venda pelo WhatsApp.",
        assigned_to="Comercial",
    )
    db.session.add(ticket)
    db.session.flush()
    db.session.add(
        InternalChatMessage(
            ticket_id=ticket.id,
            author_name="Sistema",
            message=f"Card criado automaticamente para a venda {sale.code} vinda do WhatsApp.",
        )
    )
    return ticket


def _current_cash_session():
    return CashSession.query.filter_by(status="open").order_by(CashSession.opened_at.desc(), CashSession.id.desc()).first()


def _cash_received_total(cash_session_id):
    total = db.session.query(func.coalesce(func.sum(PharmacyPayment.amount), 0)).filter(
        PharmacyPayment.cash_session_id == cash_session_id,
        PharmacyPayment.status.in_(["paid", "authorized"]),
        PharmacyPayment.method.in_(["cash", "debit_card", "credit_card", "card_machine", "pix"]),
    ).scalar()
    manual_total = db.session.query(func.coalesce(func.sum(
        case((CashMovement.direction == "in", CashMovement.amount), else_=-CashMovement.amount)
    ), 0)).filter(CashMovement.cash_session_id == cash_session_id).scalar()
    return Decimal(total or 0) + Decimal(manual_total or 0)


def _sale_paid_amount(sale_id):
    total = db.session.query(func.coalesce(func.sum(PharmacyPayment.amount), 0)).filter(
        PharmacyPayment.sale_id == sale_id,
        PharmacyPayment.status.in_(["paid", "authorized"]),
    ).scalar()
    return Decimal(total or 0)


def _sync_sale_receivable(sale):
    paid_amount = _sale_paid_amount(sale.id)
    total_amount = Decimal(sale.total_amount or 0)
    receivable = FinancialEntry.query.filter_by(source_ref=sale.code, entry_type="receivable").order_by(FinancialEntry.id.desc()).first()
    if paid_amount <= 0:
        sale.status = "open"
        if receivable:
            receivable.status = "open"
            receivable.paid_at = None
    elif paid_amount < total_amount:
        sale.status = "partially_paid"
        if receivable:
            receivable.status = "partial"
            receivable.paid_at = None
    else:
        sale.status = "paid"
        if receivable:
            receivable.status = "paid"
            receivable.paid_at = datetime.utcnow()


def _add_sale_items(sale, items, movement_type="sale"):
    subtotal = Decimal("0")
    discount_total = Decimal("0")
    for raw_item in items:
        product = None
        if raw_item.get("product_id"):
            product = db.session.get(PharmacyProduct, int(raw_item["product_id"]))
        elif raw_item.get("sku"):
            product = PharmacyProduct.query.filter(
                func.lower(PharmacyProduct.sku) == str(raw_item["sku"]).strip().lower()
            ).first()
        if not product:
            raise ValueError("Produto nao encontrado em um dos itens.")
        quantity = _to_decimal(raw_item.get("quantity"), f"quantidade de {product.name}")
        unit_price = _to_decimal(raw_item.get("unit_price"), f"preco de {product.name}", default=str(product.sale_price or "0"))
        line_discount = _to_decimal(raw_item.get("discount_amount"), f"desconto de {product.name}")
        if quantity <= 0:
            raise ValueError(f"Quantidade de {product.name} deve ser maior que zero.")
        floor_price = _margin_floor_price(product.cost_price or 0, product.category)
        final_unit_price = (unit_price - (line_discount / quantity)).quantize(Decimal("0.01"))
        if final_unit_price < floor_price:
            raise ValueError(
                f"Desconto maior que a margem permitida para {product.name}. "
                f"Preco minimo: R$ {floor_price:.2f}."
            )
        selections = _select_lots(product.id, quantity) if product.tracks_inventory else [(None, quantity)]
        remaining_discount = line_discount
        for index, (lot, consume) in enumerate(selections):
            proportional_discount = (
                remaining_discount if index == len(selections) - 1
                else (line_discount * consume / quantity).quantize(Decimal("0.01"))
            )
            remaining_discount -= proportional_discount
            line_total = (unit_price * consume - proportional_discount).quantize(Decimal("0.01"))
            if lot:
                lot.quantity_available = Decimal(lot.quantity_available or 0) - consume
            db.session.add(PharmacySaleItem(
                sale_id=sale.id, product_id=product.id, lot_id=lot.id if lot else None,
                quantity=consume, unit_price=unit_price,
                discount_amount=proportional_discount, total_amount=line_total,
            ))
            if lot:
                _log_stock_movement(
                    movement_type=movement_type, product=product, lot=lot, quantity=-consume,
                    reference_code=sale.code, notes=f"Saida por {'edicao da venda' if movement_type == 'sale_edit' else 'venda'} {sale.code}.",
                )
            subtotal += (unit_price * consume).quantize(Decimal("0.01"))
            discount_total += proportional_discount
    return subtotal, discount_total


def _restore_sale_stock(sale, movement_type, notes):
    for item in sale.items.order_by(PharmacySaleItem.id.asc()).all():
        if item.lot:
            item.lot.quantity_available = Decimal(item.lot.quantity_available or 0) + Decimal(item.quantity or 0)
            _log_stock_movement(
                movement_type=movement_type, product=item.product, lot=item.lot,
                quantity=Decimal(item.quantity or 0), reference_code=sale.code, notes=notes,
            )
        db.session.delete(item)
    db.session.flush()


def _record_sale_payment(sale, payload, amount=None):
    if sale.status == "cancelled" or sale.delivery_status == "cancelled":
        raise ValueError("Pedido cancelado nao pode receber pagamentos.")
    method = (payload.get("method") or payload.get("payment_method") or "").strip().lower()
    if method not in {"pix", "card_machine", "credit_card", "debit_card", "cash"}:
        raise ValueError("Metodo de pagamento invalido.")
    cash_session = _current_cash_session()
    if not cash_session:
        raise ValueError("Abra o caixa antes de receber uma venda.")

    balance = max(Decimal(sale.total_amount or 0) - _sale_paid_amount(sale.id), Decimal("0"))
    payment_amount = amount if amount is not None else _to_decimal(
        payload.get("amount") or payload.get("payment_amount"), "valor", default=str(balance)
    )
    if payment_amount <= 0:
        raise ValueError("O valor do pagamento deve ser maior que zero.")
    if payment_amount > balance:
        raise ValueError(f"O pagamento excede o saldo da venda de R$ {balance:.2f}.")

    settings = _setting_map()
    provider = (payload.get("provider") or "").strip() or (
        settings.get("PHARMACY_PIX_PROVIDER", "") if method == "pix" else settings.get("PHARMACY_CARD_PROVIDER", "")
    )
    reference = f"{method.upper()}-{uuid4().hex[:10].upper()}"
    payment = PharmacyPayment(
        sale_id=sale.id,
        cash_session_id=cash_session.id,
        method=method,
        provider=provider,
        amount=payment_amount,
        status="paid" if method == "cash" else "authorized",
        transaction_reference=reference,
        pix_qr_code=f"PIX|{sale.code}|{payment_amount:.2f}|{reference}" if method == "pix" else "",
        pix_copy_paste=f"000201{sale.code}{reference}" if method == "pix" else "",
        card_brand=(payload.get("card_brand") or "").strip(),
        installments=max(1, int(payload.get("installments") or 1)),
        paid_at=datetime.utcnow(),
    )
    db.session.add(payment)
    db.session.flush()
    _sync_sale_receivable(sale)
    cash_session.expected_amount = Decimal(cash_session.opening_amount or 0) + _cash_received_total(cash_session.id)
    return payment


def _summary():
    today = date.today()
    limit = today + timedelta(days=60)
    products = PharmacyProduct.query.order_by(PharmacyProduct.name.asc()).all()
    lots = PharmacyLot.query.order_by(PharmacyLot.expiration_date.asc()).all()
    purchases = PurchaseOrder.query.order_by(PurchaseOrder.created_at.desc()).limit(8).all()
    financial_entries = FinancialEntry.query.order_by(FinancialEntry.due_date.asc(), FinancialEntry.id.desc()).limit(8).all()
    payments = PharmacyPayment.query.order_by(PharmacyPayment.created_at.desc(), PharmacyPayment.id.desc()).limit(20).all()
    stock_movements = StockMovement.query.order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).limit(20).all()
    inventory_counts = InventoryCount.query.order_by(InventoryCount.count_date.desc(), InventoryCount.id.desc()).limit(10).all()
    expiring_lots = [lot for lot in lots if Decimal(lot.quantity_available or 0) > 0 and lot.expiration_date <= limit]
    low_stock = [product for product in products if _product_stock(product.id) <= Decimal(product.minimum_stock or 0)]
    no_stock = [product for product in products if _product_stock(product.id) <= Decimal("0")]
    sales_today = PharmacySale.query.filter(
        func.date(PharmacySale.created_at) == today.isoformat(),
        PharmacySale.status != "cancelled",
    ).all()
    revenue_today = sum((sale.total_amount or Decimal("0")) for sale in sales_today)
    overdue_entries = FinancialEntry.query.filter(
        FinancialEntry.status.in_(["open", "partial"]),
        FinancialEntry.due_date < today,
    ).all()
    receivable_open = db.session.query(func.coalesce(func.sum(FinancialEntry.amount), 0)).filter(
        FinancialEntry.entry_type == "receivable",
        FinancialEntry.status.in_(["open", "partial"]),
    ).scalar()
    payable_open = db.session.query(func.coalesce(func.sum(FinancialEntry.amount), 0)).filter(
        FinancialEntry.entry_type == "payable",
        FinancialEntry.status.in_(["open", "partial"]),
    ).scalar()
    cash_session = _current_cash_session()
    cash_activity = []
    if cash_session:
        for movement in CashMovement.query.filter_by(cash_session_id=cash_session.id).order_by(CashMovement.created_at.desc()).limit(20).all():
            cash_activity.append({
                "kind": "Movimento", "description": movement.description,
                "direction": movement.direction, "amount": float(movement.amount or 0),
                "occurred_at": movement.created_at.isoformat() + "Z",
            })
        for payment in PharmacyPayment.query.filter(
            PharmacyPayment.cash_session_id == cash_session.id,
            PharmacyPayment.status.in_(["paid", "authorized"]),
        ).order_by(PharmacyPayment.created_at.desc()).limit(20).all():
            cash_activity.append({
                "kind": "Recebimento", "description": payment.sale.code if payment.sale else payment.transaction_reference,
                "direction": "in", "amount": float(payment.amount or 0),
                "occurred_at": (payment.paid_at or payment.created_at).isoformat() + "Z",
            })
    cash_activity.sort(key=lambda item: item["occurred_at"], reverse=True)
    product_rows = [_serialize_product(product) for product in products]
    fiscal_crt = _setting_map().get("FISCAL_CRT", "")
    for product, row in zip(products, product_rows):
        row["fiscal_errors"] = validate_product(product, fiscal_crt, "65")
        row["fiscal_ready"] = not row["fiscal_errors"]
    stock_quantity = sum(Decimal(str(product["stock"])) for product in product_rows if product["tracks_inventory"])
    stock_sale_value = sum(
        Decimal(str(product["stock"])) * Decimal(str(product["sale_price"]))
        for product in product_rows if product["tracks_inventory"]
    )
    stock_cost_value = sum(
        Decimal(str(product["stock"])) * Decimal(str(product["cost_price"]))
        for product in product_rows if product["tracks_inventory"]
    )
    order_status_counts = {status: 0 for status in ("new", "ready", "out_for_delivery", "delivered", "completed", "cancelled")}
    for status, count in db.session.query(PharmacySale.delivery_status, func.count(PharmacySale.id)).group_by(PharmacySale.delivery_status).all():
        normalized = "new" if status == "picking" else status
        if normalized in order_status_counts:
            order_status_counts[normalized] += int(count)
    payment_method_totals = {}
    for payment in PharmacyPayment.query.filter(PharmacyPayment.status.in_(["paid", "authorized"])).all():
        key = payment.method or "outros"
        payment_method_totals[key] = payment_method_totals.get(key, 0.0) + float(payment.amount or 0)
    paid_entries = FinancialEntry.query.filter_by(status="paid").order_by(FinancialEntry.updated_at.desc(), FinancialEntry.id.desc()).limit(20).all()
    unpaid_entries = FinancialEntry.query.filter(FinancialEntry.status.in_(["open", "partial"])).order_by(FinancialEntry.due_date.asc(), FinancialEntry.id.desc()).limit(20).all()
    stages = WorkflowStage.query.order_by(WorkflowStage.order_index.asc(), WorkflowStage.id.asc()).all()
    tickets = WorkflowTicket.query.order_by(WorkflowTicket.updated_at.desc(), WorkflowTicket.id.desc()).all()
    report_sales = PharmacySale.query.order_by(PharmacySale.created_at.desc(), PharmacySale.id.desc()).all()
    cash_report = _cash_report()
    return {
        "products_count": len(products),
        "active_lots_count": len([lot for lot in lots if Decimal(lot.quantity_available or 0) > 0]),
        "expiring_lots_count": len(expiring_lots),
        "low_stock_count": len(low_stock),
        "no_stock_count": len(no_stock),
        "sales_today_count": len(sales_today),
        "purchases_count": PurchaseOrder.query.count(),
        "financial_open_count": FinancialEntry.query.filter(FinancialEntry.status.in_(["open", "partial"])).count(),
        "overdue_financial_count": len(overdue_entries),
        "revenue_today": float(revenue_today),
        "receivable_open": float(Decimal(receivable_open or 0)),
        "payable_open": float(Decimal(payable_open or 0)),
        "cash_status": cash_session.status if cash_session else "closed",
        "cash_opening_amount": float(cash_session.opening_amount or 0) if cash_session else 0.0,
        "cash_expected_amount": float(cash_session.expected_amount or 0) if cash_session else 0.0,
        "products": product_rows,
        "stock_quantity": float(stock_quantity),
        "stock_sale_value": float(stock_sale_value),
        "stock_cost_value": float(stock_cost_value),
        "order_status_counts": order_status_counts,
        "all_lots": [_serialize_lot(lot) for lot in lots],
        "active_lots": [_serialize_lot(lot) for lot in lots if Decimal(lot.quantity_available or 0) > 0],
        "expiring_lots": [_serialize_lot(lot) for lot in expiring_lots],
        "low_stock_products": [_serialize_product(product) for product in low_stock],
        "no_stock_products": [_serialize_product(product) for product in no_stock],
        "recent_sales": [_serialize_sale(sale) for sale in PharmacySale.query.order_by(PharmacySale.created_at.desc()).limit(8).all()],
        "pending_sales": [
            _serialize_sale(sale)
            for sale in PharmacySale.query.order_by(PharmacySale.created_at.desc(), PharmacySale.id.desc()).all()
            if _sale_paid_amount(sale.id) < Decimal(sale.total_amount or 0)
        ],
        "customers": [_serialize_customer(customer) for customer in PharmacyCustomer.query.order_by(PharmacyCustomer.name.asc()).all()],
        "report_sales": [_serialize_sale_report(sale) for sale in report_sales],
        "cash_report": cash_report,
        "cash_movements": [_serialize_cash_movement(movement) for movement in CashMovement.query.order_by(CashMovement.created_at.desc(), CashMovement.id.desc()).limit(50).all()],
        "cash_activity": cash_activity[:20],
        "recent_purchases": [_serialize_purchase(purchase) for purchase in purchases],
        "financial_entries": [_serialize_financial_entry(entry) for entry in financial_entries],
        "paid_financial_entries": [_serialize_financial_entry(entry) for entry in paid_entries],
        "unpaid_financial_entries": [_serialize_financial_entry(entry) for entry in unpaid_entries],
        "recent_payments": [_serialize_payment(payment) for payment in payments],
        "payment_method_totals": payment_method_totals,
        "recent_stock_movements": [_serialize_stock_movement(movement) for movement in stock_movements],
        "inventory_counts": [_serialize_inventory_count(count) for count in inventory_counts],
        "workflow_stages": [
            {
                "id": stage.id,
                "name": stage.name,
                "color": stage.color,
                "is_closed": stage.is_closed,
                "tickets": [_serialize_ticket(ticket) for ticket in stage.tickets.order_by(WorkflowTicket.updated_at.desc(), WorkflowTicket.id.desc()).all()],
            }
            for stage in stages
        ],
        "workflow_tickets": [_serialize_ticket(ticket) for ticket in tickets[:10]],
        "cash_session": {
            "id": cash_session.id,
            "status": cash_session.status,
            "opened_at": cash_session.opened_at.isoformat() if cash_session else "",
            "opening_amount": float(cash_session.opening_amount or 0) if cash_session else 0.0,
            "expected_amount": float(cash_session.expected_amount or 0) if cash_session else 0.0,
        } if cash_session else None,
    }


def _select_lots(product_id, requested_quantity):
    remaining = requested_quantity
    selected = []
    lots = PharmacyLot.query.filter(
        PharmacyLot.product_id == product_id,
        PharmacyLot.quantity_available > 0,
    ).order_by(PharmacyLot.expiration_date.asc(), PharmacyLot.received_at.asc(), PharmacyLot.id.asc()).all()
    for lot in lots:
        if remaining <= 0:
            break
        available = Decimal(lot.quantity_available or 0)
        if available <= 0:
            continue
        consume = min(available, remaining)
        selected.append((lot, consume))
        remaining -= consume
    if remaining > 0:
        raise ValueError("Estoque insuficiente para concluir a venda.")
    return selected


@bp.route("/")
def index():
    summary = _summary()
    mode_key, store_mode = resolve_store_mode(_setting_map().get("STORE_MODE"))
    fiscal_history = FiscalSimulation.query.order_by(FiscalSimulation.created_at.desc(), FiscalSimulation.id.desc()).limit(50).all()
    local_tz = ZoneInfo(os.environ.get("TZ", "America/Sao_Paulo"))
    local_today = datetime.now(local_tz).date()
    day_start = datetime.combine(local_today, time.min, local_tz).astimezone(timezone.utc).replace(tzinfo=None)
    day_end = datetime.combine(local_today + timedelta(days=1), time.min, local_tz).astimezone(timezone.utc).replace(tzinfo=None)
    kanban_sales = PharmacySale.query.filter(
        PharmacySale.status != "cancelled",
        or_(
            PharmacySale.delivery_status != "completed",
            and_(PharmacySale.completed_at >= day_start, PharmacySale.completed_at < day_end),
        ),
    ).order_by(PharmacySale.created_at.desc(), PharmacySale.id.desc()).limit(200).all()
    menu_sections = [
        {"id": "inicio", "title": "Inicio", "description": "Visao geral e indicadores"},
        {"id": "workflow", "title": "Workflow", "description": "Kanban, WhatsApp e chat interno"},
        {"id": "cadastros", "title": "Cadastros", "description": "Produtos, categorias e fornecedores"},
        {"id": "lancamentos", "title": "Lancamentos", "description": "Lotes, vendas, compras e financeiro"},
        {"id": "estoque", "title": "Estoque", "description": "Posicao atual, lotes e movimentacoes"},
        {"id": "faturamento", "title": "Faturamento", "description": "Notas individuais e em massa das vendas"},
        {"id": "relatorios", "title": "Relatorios", "description": "Estoque, vencimentos, caixa e performance"},
        {"id": "documentacao", "title": "Documentacao", "description": "Procedimentos de operacao do NanoStore"},
        {"id": "configuracao", "title": "Configuracao", "description": "Provedores e canais de integracao"},
    ]
    return render_template(
        "index.html",
        title="NanoStore",
        summary=summary,
        categories=PharmacyCategory.query.order_by(PharmacyCategory.name.asc()).all(),
        suppliers=PharmacySupplier.query.order_by(PharmacySupplier.name.asc()).all(),
        customers=PharmacyCustomer.query.order_by(PharmacyCustomer.name.asc()).all(),
        distribution_tables=DistributionTable.query.filter_by(is_active=True).order_by(DistributionTable.number.asc()).all(),
        settings_map=_setting_map(),
        https_runtime=_https_runtime_config(),
        fiscal_status=fiscal_certificate_status(),
        fiscal_sales=PharmacySale.query.filter(
            PharmacySale.status != "cancelled"
        ).order_by(PharmacySale.created_at.desc(), PharmacySale.id.desc()).limit(200).all(),
        kanban_sales=kanban_sales,
        fiscal_simulations=[_serialize_fiscal_simulation(item) for item in fiscal_history],
        menu_sections=menu_sections,
        mode_key=mode_key,
        store_mode=store_mode,
        store_modes=STORE_MODES,
    )


@bp.route("/healthz")
def healthz():
    return jsonify({"ok": True, "status": "up"})


@bp.route("/mobile-setup")
def mobile_setup():
    https_runtime = _https_runtime_config()
    host = _normalize_host(request.host)
    forwarded_host = _normalize_host(request.headers.get("X-Forwarded-Host", ""))
    current_host = forwarded_host or host or "127.0.0.1"
    forwarded_prefix = (request.headers.get("X-Forwarded-Prefix") or "").rstrip("/")
    http_base = f"http://{current_host}:{https_runtime['http_port']}{forwarded_prefix}"
    https_base = https_runtime["public_base_url"].rstrip("/") or (
        f"https://{current_host}:{https_runtime['https_port']}{forwarded_prefix}"
    )
    cert_hosts = https_runtime["cert_hosts"]
    host_covered = current_host in cert_hosts or current_host in {"127.0.0.1", "localhost"}
    return render_template(
        "mobile_setup.html",
        host=current_host,
        http_base=http_base,
        https_base=https_base,
        ca_url=f"{http_base}/api/ca/cert.crt",
        cert_hosts=cert_hosts,
        host_covered=host_covered,
    )


@bp.route("/api/dashboard")
def api_dashboard():
    return jsonify({"ok": True, **_summary()})


@bp.route("/api/categories", methods=["GET", "POST"])
def api_categories():
    if request.method == "GET":
        categories = PharmacyCategory.query.order_by(PharmacyCategory.name.asc()).all()
        return jsonify(
            {
                "ok": True,
                "items": [
                    _serialize_category(category)
                    for category in categories
                ],
            }
        )
    payload = request.get_json(force=True)
    name = (payload.get("name") or "").strip()
    if not name:
        abort(400, "Nome obrigatorio.")
    row = PharmacyCategory(
        name=name,
        description=(payload.get("description") or "").strip(),
        minimum_profit_margin=_to_decimal(payload.get("minimum_profit_margin"), "margem minima"),
        suggested_profit_margin=_to_decimal(payload.get("suggested_profit_margin"), "margem sugerida"),
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "id": row.id})


@bp.route("/api/categories/<int:category_id>", methods=["PATCH"])
def api_category_update(category_id):
    category = db.session.get(PharmacyCategory, category_id) or abort(404, "Categoria nao encontrada.")
    payload = request.get_json(force=True)
    if "name" in payload:
        category.name = (payload.get("name") or category.name).strip()
    if "description" in payload:
        category.description = (payload.get("description") or "").strip()
    if "minimum_profit_margin" in payload:
        category.minimum_profit_margin = _to_decimal(payload.get("minimum_profit_margin"), "margem minima")
    if "suggested_profit_margin" in payload:
        category.suggested_profit_margin = _to_decimal(payload.get("suggested_profit_margin"), "margem sugerida")
    db.session.commit()
    return jsonify({"ok": True, "category": _serialize_category(category)})


@bp.route("/api/suppliers", methods=["GET", "POST"])
def api_suppliers():
    if request.method == "GET":
        suppliers = PharmacySupplier.query.order_by(PharmacySupplier.name.asc()).all()
        return jsonify(
            {
                "ok": True,
                "items": [
                    {
                        "id": supplier.id,
                        "name": supplier.name,
                        "document": supplier.document or "",
                        "phone": supplier.phone or "",
                        "email": supplier.email or "",
                    }
                    for supplier in suppliers
                ],
            }
        )
    payload = request.get_json(force=True)
    name = (payload.get("name") or "").strip()
    if not name:
        abort(400, "Nome obrigatorio.")
    row = PharmacySupplier(
        name=name,
        document=(payload.get("document") or "").strip(),
        phone=(payload.get("phone") or "").strip(),
        email=(payload.get("email") or "").strip(),
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "id": row.id})


@bp.route("/api/customers", methods=["GET", "POST"])
def api_customers():
    if request.method == "GET":
        rows = PharmacyCustomer.query.order_by(PharmacyCustomer.name.asc()).all()
        return jsonify({"ok": True, "items": [_serialize_customer(row) for row in rows]})
    payload = request.get_json(force=True)
    name = (payload.get("name") or "").strip()
    phone = "".join(char for char in str(payload.get("phone") or "") if char.isdigit())
    address = (payload.get("address") or "").strip()
    if not name:
        abort(400, "Nome do cliente e obrigatorio.")
    if not phone or not address:
        abort(400, "Telefone e endereco do cliente sao obrigatorios.")
    row = PharmacyCustomer(
        name=name, document=(payload.get("document") or "").strip(), phone=phone, address=address,
        address_number=(payload.get("address_number") or "").strip(), neighborhood=(payload.get("neighborhood") or "").strip(),
        city=(payload.get("city") or "").strip(), state=(payload.get("state") or "").strip().upper(),
        postal_code=(payload.get("postal_code") or "").strip(), notes=(payload.get("notes") or "").strip(),
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "customer": _serialize_customer(row)})


@bp.route("/api/tables")
def api_tables():
    rows = DistributionTable.query.order_by(DistributionTable.number.asc()).all()
    return jsonify({"ok": True, "items": [
        {"id": row.id, "number": row.number, "name": row.name, "location": row.location,
         "reference": row.reference, "is_active": row.is_active}
        for row in rows
    ]})


@bp.route("/api/products", methods=["GET", "POST"])
def api_products():
    if request.method == "GET":
        products = PharmacyProduct.query.order_by(PharmacyProduct.name.asc()).all()
        return jsonify({"ok": True, "items": [_serialize_product(product) for product in products]})
    payload = request.get_json(force=True)
    name = (payload.get("name") or "").strip()
    sku = (payload.get("sku") or "").strip()
    barcode = (payload.get("barcode") or "").strip()
    if not name or not sku:
        abort(400, "Nome e SKU sao obrigatorios.")
    if PharmacyProduct.query.filter(func.lower(PharmacyProduct.sku) == sku.lower()).first():
        abort(400, "SKU ja cadastrado em outro produto.")
    if barcode and PharmacyProduct.query.filter(func.lower(PharmacyProduct.barcode) == barcode.lower()).first():
        abort(400, "Codigo de barras ja cadastrado em outro produto.")
    category = db.session.get(PharmacyCategory, payload.get("category_id")) if payload.get("category_id") else None
    cost_price = _to_decimal(payload.get("cost_price"), "preco de custo")
    sale_price = _to_decimal(payload.get("sale_price"), "preco de venda")
    if sale_price <= 0 and category and Decimal(category.suggested_profit_margin or 0) > 0:
        sale_price = (cost_price * (Decimal("1") + (Decimal(category.suggested_profit_margin or 0) / Decimal("100")))).quantize(Decimal("0.01"))
    product = PharmacyProduct(
        sku=sku,
        name=name,
        barcode=barcode or None,
        brand=(payload.get("brand") or "").strip(),
        active_ingredient=(payload.get("active_ingredient") or "").strip(),
        unit=(payload.get("unit") or "un").strip() or "un",
        sale_price=sale_price,
        cost_price=cost_price,
        minimum_stock=_to_decimal(payload.get("minimum_stock"), "estoque minimo"),
        requires_prescription=_to_bool(payload.get("requires_prescription")),
        is_controlled=_to_bool(payload.get("is_controlled")),
        is_active=not str(payload.get("is_active", "true")).strip().lower() in {"0", "false", "off", "nao"},
        tracks_inventory=_to_bool(payload.get("tracks_inventory", True)),
        category_id=category.id if category else None,
        supplier_id=payload.get("supplier_id") or None,
    )
    _apply_product_tax(product, payload)
    db.session.add(product)
    db.session.commit()
    return jsonify({"ok": True, "product": _serialize_product(product)})


def _apply_product_tax(product, payload):
    if "tracks_inventory" in payload:
        product.tracks_inventory = _to_bool(payload.get("tracks_inventory"))
    text_fields = (
        "ncm", "cest", "cfop", "fiscal_origin", "icms_cst", "pis_cst", "cofins_cst",
        "tax_unit", "gtin_taxable", "benefit_code", "anvisa_code", "ibs_cbs_cst", "tax_classification",
    )
    for field in text_fields:
        if field in payload:
            value = str(payload.get(field) or "").strip().upper()
            setattr(product, field, value)
    if "has_tax_benefit" in payload:
        product.has_tax_benefit = _to_bool(payload.get("has_tax_benefit"))
    for field in ("max_consumer_price", "ibs_uf_rate", "ibs_mun_rate", "cbs_rate"):
        if field in payload:
            setattr(product, field, _to_decimal(payload.get(field), field))


@bp.route("/api/fiscal/product-assistance", methods=["POST"])
def api_product_fiscal_assistance():
    payload = request.get_json(force=True) or {}
    settings = _setting_map()
    profile = icms_code_profile(settings.get("FISCAL_CRT", ""))
    barcode = str(payload.get("barcode") or "").strip()
    unit = str(payload.get("unit") or "UN").strip().upper()[:6] or "UN"
    suggestions = {
        "cfop": str(payload.get("cfop") or "5102").strip(),
        "fiscal_origin": str(payload.get("fiscal_origin") or "0").strip(),
        "tax_unit": str(payload.get("tax_unit") or unit).strip().upper(),
        "gtin_taxable": str(payload.get("gtin_taxable") or (barcode if valid_gtin(barcode) else "SEM GTIN")).strip().upper(),
    }
    candidate_values = {
        "sku": str(payload.get("sku") or "ITEM").strip(),
        "name": str(payload.get("name") or "Produto").strip(),
        "ncm": str(payload.get("ncm") or "").strip(),
        "cest": str(payload.get("cest") or "").strip(),
        "icms_cst": str(payload.get("icms_cst") or "").strip(),
        "pis_cst": str(payload.get("pis_cst") or "").strip(),
        "cofins_cst": str(payload.get("cofins_cst") or "").strip(),
        "benefit_code": str(payload.get("benefit_code") or "").strip(),
        "has_tax_benefit": _to_bool(payload.get("has_tax_benefit")),
        "anvisa_code": str(payload.get("anvisa_code") or "").strip(),
        "max_consumer_price": _to_decimal(payload.get("max_consumer_price"), "PMC"),
        "ibs_cbs_cst": str(payload.get("ibs_cbs_cst") or "").strip(),
        "tax_classification": str(payload.get("tax_classification") or "").strip(),
        "ibs_uf_rate": _to_decimal(payload.get("ibs_uf_rate"), "IBS UF"),
        "ibs_mun_rate": _to_decimal(payload.get("ibs_mun_rate"), "IBS municipal"),
        "cbs_rate": _to_decimal(payload.get("cbs_rate"), "CBS"),
        **suggestions,
    }
    candidate = SimpleNamespace(**candidate_values)
    return jsonify({
        "ok": True,
        "crt": str(settings.get("FISCAL_CRT", "")).strip(),
        "regime_configured": profile["configured"],
        "field_label": profile["field"],
        "expected_digits": profile["digits"],
        "options": [{"code": code, "label": label} for code, label in profile["options"]],
        "suggestions": suggestions,
        "fiscal_errors": validate_product(candidate, settings.get("FISCAL_CRT", ""), payload.get("document_model", "65")),
    })


@bp.route("/api/settings/store-mode", methods=["POST"])
def api_store_mode():
    payload = request.get_json(force=True)
    mode_key = str(payload.get("mode") or "").strip().lower()
    if mode_key not in STORE_MODES:
        abort(400, "Modo de apresentacao invalido.")
    _set_setting("STORE_MODE", mode_key)
    db.session.commit()
    return jsonify({"ok": True, "mode": mode_key, "profile": STORE_MODES[mode_key]})


@bp.route("/api/products/<int:product_id>", methods=["PATCH"])
def api_product_update(product_id):
    product = db.session.get(PharmacyProduct, product_id) or abort(404, "Produto nao encontrado.")
    payload = request.get_json(force=True)
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            abort(400, "Nome e obrigatorio.")
        product.name = name
    if "sku" in payload:
        sku = str(payload.get("sku") or "").strip()
        if not sku:
            abort(400, "SKU e obrigatorio.")
        duplicate = PharmacyProduct.query.filter(
            PharmacyProduct.id != product.id,
            func.lower(PharmacyProduct.sku) == sku.lower(),
        ).first()
        if duplicate:
            abort(400, "SKU ja cadastrado em outro produto.")
        product.sku = sku
    if "barcode" in payload:
        barcode = str(payload.get("barcode") or "").strip()
        duplicate = barcode and PharmacyProduct.query.filter(
            PharmacyProduct.id != product.id,
            func.lower(PharmacyProduct.barcode) == barcode.lower(),
        ).first()
        if duplicate:
            abort(400, "Codigo de barras ja cadastrado em outro produto.")
        product.barcode = barcode or None
    for field in ("brand", "active_ingredient"):
        if field in payload:
            setattr(product, field, str(payload.get(field) or "").strip())
    if "unit" in payload:
        product.unit = str(payload.get("unit") or "un").strip() or "un"
    for field, label in (
        ("cost_price", "preco de custo"),
        ("sale_price", "preco de venda"),
        ("minimum_stock", "estoque minimo"),
    ):
        if field in payload:
            setattr(product, field, _to_decimal(payload.get(field), label))
    for field in ("requires_prescription", "is_controlled", "is_active"):
        if field in payload:
            setattr(product, field, _to_bool(payload.get(field)))
    if "category_id" in payload:
        category_id = payload.get("category_id") or None
        if category_id and not db.session.get(PharmacyCategory, category_id):
            abort(400, "Categoria nao encontrada.")
        product.category_id = category_id
    if "supplier_id" in payload:
        supplier_id = payload.get("supplier_id") or None
        if supplier_id and not db.session.get(PharmacySupplier, supplier_id):
            abort(400, "Fornecedor nao encontrado.")
        product.supplier_id = supplier_id
    _apply_product_tax(product, payload)
    db.session.commit()
    settings = _setting_map()
    errors = validate_product(product, settings.get("FISCAL_CRT", ""), payload.get("document_model", "65"))
    return jsonify({"ok": True, "product": _serialize_product(product), "fiscal_errors": errors})


@bp.route("/api/products/lookup")
def api_products_lookup():
    code = (request.args.get("code") or "").strip()
    if not code:
        abort(400, "Codigo obrigatorio.")
    normalized = code.lower()
    product = None
    if normalized:
        product = PharmacyProduct.query.filter(func.lower(PharmacyProduct.barcode) == normalized).first()
        if not product:
            product = PharmacyProduct.query.filter(func.lower(PharmacyProduct.sku) == normalized).first()
        if not product:
            product = PharmacyProduct.query.filter(func.lower(PharmacyProduct.name).like(f"%{normalized}%")).order_by(PharmacyProduct.name.asc()).first()
    if not product:
        abort(404, "Item nao encontrado.")
    lots = PharmacyLot.query.filter(
        PharmacyLot.product_id == product.id,
        PharmacyLot.quantity_available > 0,
    ).order_by(PharmacyLot.expiration_date.asc(), PharmacyLot.received_at.asc(), PharmacyLot.id.asc()).all()
    return jsonify(
        {
            "ok": True,
            "product": _serialize_product(product),
            "lots": [_serialize_lot(lot) for lot in lots],
        }
    )


@bp.route("/api/app/cert.pem")
def api_app_cert_pem():
    pem_bytes, _ = _load_pem_certificate(_cert_path("nanostore-app.crt"), "HTTPS")
    response = Response(pem_bytes, mimetype="application/x-pem-file")
    response.headers["Content-Disposition"] = 'attachment; filename="nanostore-web.pem"'
    return response


@bp.route("/api/app/cert.crt")
def api_app_cert_crt():
    _, der_bytes = _load_pem_certificate(_cert_path("nanostore-app.crt"), "HTTPS")
    response = Response(der_bytes, mimetype="application/x-x509-ca-cert")
    response.headers["Content-Disposition"] = 'attachment; filename="nanostore-web.crt"'
    return response


@bp.route("/api/ca/cert.pem")
def api_ca_cert_pem():
    pem_bytes, _ = _load_pem_certificate(_cert_path("nanostore-ca.crt"), "CA")
    response = Response(pem_bytes, mimetype="application/x-pem-file")
    response.headers["Content-Disposition"] = 'attachment; filename="nanostore-ca.pem"'
    return response


@bp.route("/api/ca/cert.crt")
def api_ca_cert_crt():
    _, der_bytes = _load_pem_certificate(_cert_path("nanostore-ca.crt"), "CA")
    response = Response(der_bytes, mimetype="application/x-x509-ca-cert")
    response.headers["Content-Disposition"] = 'attachment; filename="nanostore-ca.crt"'
    return response


@bp.route("/api/lots", methods=["GET", "POST"])
def api_lots():
    if request.method == "GET":
        lots = PharmacyLot.query.order_by(PharmacyLot.expiration_date.asc(), PharmacyLot.id.asc()).all()
        return jsonify({"ok": True, "items": [_serialize_lot(lot) for lot in lots]})
    payload = request.get_json(force=True)
    product = db.session.get(PharmacyProduct, payload.get("product_id")) or abort(400, "Produto obrigatorio.")
    quantity_received = _to_decimal(payload.get("quantity_received"), "quantidade recebida")
    quantity_available = _to_decimal(payload.get("quantity_available"), "quantidade disponivel", default=str(quantity_received))
    lot = PharmacyLot(
        product_id=product.id,
        supplier_id=payload.get("supplier_id") or product.supplier_id,
        lot_code=(payload.get("lot_code") or "").strip(),
        expiration_date=_parse_date(payload.get("expiration_date"), "Validade"),
        received_at=_parse_date(payload.get("received_at"), "Recebimento"),
        quantity_received=quantity_received,
        quantity_available=quantity_available,
        purchase_price=_to_decimal(payload.get("purchase_price"), "preco de compra"),
        location=(payload.get("location") or "").strip(),
    )
    if not lot.lot_code:
        abort(400, "Codigo do lote obrigatorio.")
    db.session.add(lot)
    db.session.flush()
    _log_stock_movement(
        movement_type="entry",
        product=product,
        lot=lot,
        quantity=quantity_available,
        reference_code=lot.lot_code,
        notes="Entrada manual de lote.",
    )
    db.session.commit()
    return jsonify({"ok": True, "lot": _serialize_lot(lot)})


@bp.route("/api/sales", methods=["POST"])
def api_sales():
    payload = request.get_json(force=True)
    items = payload.get("items") or []
    if not items:
        abort(400, "Informe ao menos um item.")
    customer = db.session.get(PharmacyCustomer, payload.get("customer_id")) if payload.get("customer_id") else None
    fulfillment_type = (payload.get("fulfillment_type") or "counter").strip().lower()
    if fulfillment_type not in {"counter", "table", "delivery"}:
        abort(400, "Destino do pedido invalido.")
    customer_name = (payload.get("customer_name") or (customer.name if customer else "")).strip()
    if not customer_name:
        abort(400, "Cliente obrigatorio.")
    customer_phone = "".join(ch for ch in str(payload.get("customer_phone") or (customer.phone if customer else "")) if ch.isdigit())
    selected_table = db.session.get(DistributionTable, payload.get("table_id")) if payload.get("table_id") else None
    table_reference = selected_table.reference if selected_table else (payload.get("table_reference") or "").strip()
    delivery_address = (payload.get("delivery_address") or (customer and _serialize_customer(customer)["full_address"]) or "").strip()
    if fulfillment_type == "table" and (not selected_table or not selected_table.is_active):
        abort(400, "Selecione uma mesa cadastrada e ativa para o pedido.")
    if fulfillment_type == "delivery":
        if not customer:
            abort(400, "Selecione um cliente cadastrado para entrega.")
        if not customer_phone or not delivery_address:
            abort(400, "Entrega exige telefone e endereco do cliente.")
    sale = PharmacySale(
        code=(payload.get("code") or f"NS-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid4().hex[:5].upper()}").strip(),
        customer_name=customer_name,
        customer_phone=customer_phone,
        source_channel=(payload.get("source_channel") or "balcao").strip().lower(),
        status="open",
        notes=(payload.get("notes") or "").strip(),
        external_order_id=(payload.get("external_order_id") or "").strip(),
        customer_id=customer.id if customer else None,
        fulfillment_type=fulfillment_type,
        table_reference=table_reference,
        delivery_address=delivery_address,
        delivery_status="new",
    )
    db.session.add(sale)
    db.session.flush()

    try:
        subtotal, discount_total = _add_sale_items(sale, items)
        sale.subtotal_amount = subtotal
        sale.discount_amount = discount_total
        sale.total_amount = (subtotal - discount_total).quantize(Decimal("0.01"))
        if sale.total_amount > 0:
            db.session.add(
                FinancialEntry(
                    entry_type="receivable",
                    category="Venda",
                    description=f"Recebimento da venda {sale.code}",
                    counterparty=sale.customer_name,
                    amount=sale.total_amount,
                    status="open",
                    due_date=date.today(),
                    source_ref=sale.code,
                    notes=sale.notes,
                )
            )
        payment = None
        payment_method = (payload.get("payment_method") or "pending").strip().lower()
        if payment_method != "pending":
            payment = _record_sale_payment(sale, payload)
        _ensure_workflow_ticket_for_sale(sale)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        abort(400, str(exc))
    return jsonify({
        "ok": True,
        "sale": _serialize_sale(sale),
        "payment": _serialize_payment(payment) if payment else None,
    })


@bp.route("/api/sales/<int:sale_id>", methods=["GET", "PATCH", "DELETE"])
def api_sale_detail(sale_id):
    sale = db.session.get(PharmacySale, sale_id) or abort(404, "Pedido nao encontrado.")
    if request.method == "GET":
        return jsonify({"ok": True, "sale": _serialize_sale(sale)})
    if sale.status == "cancelled" or sale.delivery_status == "cancelled":
        abort(400, "Pedido ja cancelado.")

    if request.method == "DELETE":
        active_payments = sale.payments.filter(PharmacyPayment.status.in_(["paid", "authorized"])).all()
        current_cash = _current_cash_session()
        refund_outside_current = sum(
            (Decimal(payment.amount or 0) for payment in active_payments
             if not current_cash or payment.cash_session_id != current_cash.id),
            Decimal("0"),
        )
        if refund_outside_current > 0 and not current_cash:
            abort(400, "Abra o caixa para registrar o estorno deste pedido.")
        try:
            _restore_sale_stock(
                sale, "sale_cancel", f"Retorno ao estoque pelo cancelamento da venda {sale.code}.",
            )
            for payment in active_payments:
                payment.status = "reversed"
            if refund_outside_current > 0:
                db.session.add(CashMovement(
                    cash_session_id=current_cash.id, direction="out", category="Estorno de venda",
                    description=f"Estorno do pedido {sale.code}", amount=refund_outside_current,
                ))
            sale.status = "cancelled"
            sale.delivery_status = "cancelled"
            receivable = FinancialEntry.query.filter_by(
                source_ref=sale.code, entry_type="receivable"
            ).order_by(FinancialEntry.id.desc()).first()
            if receivable:
                receivable.status = "cancelled"
                receivable.paid_at = None
            if current_cash:
                db.session.flush()
                current_cash.expected_amount = Decimal(current_cash.opening_amount or 0) + _cash_received_total(current_cash.id)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            abort(400, str(exc))
        return jsonify({
            "ok": True, "sale": _serialize_sale(sale),
            "refunded_amount": float(sum((Decimal(payment.amount or 0) for payment in active_payments), Decimal("0"))),
        })

    payload = request.get_json(force=True)
    items = payload.get("items") or []
    if not items:
        abort(400, "Informe ao menos um item.")
    customer = db.session.get(PharmacyCustomer, payload.get("customer_id")) if payload.get("customer_id") else None
    fulfillment_type = (payload.get("fulfillment_type") or sale.fulfillment_type or "counter").strip().lower()
    customer_name = (payload.get("customer_name") or (customer.name if customer else "")).strip()
    customer_phone = "".join(ch for ch in str(payload.get("customer_phone") or (customer.phone if customer else "")) if ch.isdigit())
    selected_table = db.session.get(DistributionTable, payload.get("table_id")) if payload.get("table_id") else None
    table_reference = selected_table.reference if selected_table else (payload.get("table_reference") or "").strip()
    delivery_address = (payload.get("delivery_address") or (customer and _serialize_customer(customer)["full_address"]) or "").strip()
    if fulfillment_type not in {"counter", "table", "delivery"}:
        abort(400, "Destino do pedido invalido.")
    if not customer_name:
        abort(400, "Cliente obrigatorio.")
    if fulfillment_type == "table" and (not selected_table or not selected_table.is_active):
        abort(400, "Selecione uma mesa cadastrada e ativa para o pedido.")
    if fulfillment_type == "delivery" and (not customer or not customer_phone or not delivery_address):
        abort(400, "Entrega exige cliente cadastrado, telefone e endereco.")

    paid_amount = _sale_paid_amount(sale.id)
    try:
        _restore_sale_stock(sale, "sale_edit_return", f"Retorno temporario pela edicao da venda {sale.code}.")
        subtotal, discount_total = _add_sale_items(sale, items, movement_type="sale_edit")
        total_amount = (subtotal - discount_total).quantize(Decimal("0.01"))
        if total_amount < paid_amount:
            raise ValueError(
                f"O novo total nao pode ser menor que o valor ja recebido de R$ {paid_amount:.2f}. "
                "Cancele o pedido para realizar o estorno."
            )
        sale.customer_name = customer_name
        sale.customer_phone = customer_phone
        sale.customer_id = customer.id if customer else None
        sale.fulfillment_type = fulfillment_type
        sale.table_reference = table_reference if fulfillment_type == "table" else ""
        sale.delivery_address = delivery_address if fulfillment_type == "delivery" else ""
        sale.source_channel = (payload.get("source_channel") or sale.source_channel).strip().lower()
        sale.external_order_id = (payload.get("external_order_id") or "").strip()
        sale.notes = (payload.get("notes") or "").strip()
        sale.subtotal_amount = subtotal
        sale.discount_amount = discount_total
        sale.total_amount = total_amount
        receivable = FinancialEntry.query.filter_by(
            source_ref=sale.code, entry_type="receivable"
        ).order_by(FinancialEntry.id.desc()).first()
        if receivable:
            receivable.amount = total_amount
            receivable.counterparty = customer_name
            receivable.notes = sale.notes
        elif total_amount > 0:
            db.session.add(FinancialEntry(
                entry_type="receivable", category="Venda", description=f"Recebimento da venda {sale.code}",
                counterparty=customer_name, amount=total_amount, status="open",
                due_date=date.today(), source_ref=sale.code, notes=sale.notes,
            ))
        db.session.flush()
        _sync_sale_receivable(sale)
        db.session.commit()
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        abort(400, str(exc))
    return jsonify({"ok": True, "sale": _serialize_sale(sale)})


@bp.route("/api/sales/<int:sale_id>/fulfillment", methods=["PATCH"])
def api_sale_fulfillment(sale_id):
    sale = db.session.get(PharmacySale, sale_id) or abort(404, "Pedido nao encontrado.")
    if sale.status == "cancelled" or sale.delivery_status == "cancelled":
        abort(400, "Pedido cancelado nao pode mudar de etapa.")
    payload = request.get_json(force=True)
    status = (payload.get("delivery_status") or "").strip().lower()
    allowed = {"new", "picking", "ready", "out_for_delivery", "delivered", "completed", "cancelled"}
    if status not in allowed:
        abort(400, "Status de separacao ou entrega invalido.")
    sale.delivery_status = status
    sale.completed_at = datetime.now(timezone.utc).replace(tzinfo=None) if status == "completed" else None
    db.session.commit()
    return jsonify({"ok": True, "sale": _serialize_sale(sale)})


@bp.route("/api/fiscal/status")
def api_fiscal_status():
    return jsonify({"ok": True, **fiscal_certificate_status()})


@bp.route("/api/fiscal/simulations", methods=["POST"])
def api_fiscal_simulations():
    payload = request.get_json(force=True)
    raw_sale_ids = payload.get("sale_ids")
    if raw_sale_ids is None and payload.get("sale_id") is not None:
        raw_sale_ids = [payload.get("sale_id")]
    if not isinstance(raw_sale_ids, list) or not raw_sale_ids:
        abort(400, "Selecione ao menos uma venda para faturar.")

    sale_ids = []
    for raw_sale_id in raw_sale_ids:
        try:
            sale_id = int(raw_sale_id)
        except (TypeError, ValueError):
            abort(400, "Identificador de venda invalido.")
        if sale_id not in sale_ids:
            sale_ids.append(sale_id)
    if len(sale_ids) > 100:
        abort(400, "O faturamento em massa aceita no maximo 100 vendas por lote.")

    document_model = str(payload.get("document_model") or "65").strip()
    if document_model not in {"55", "65"}:
        abort(400, "Modelo fiscal deve ser 55 ou 65.")

    try:
        identity = load_fiscal_identity()
        settings = _setting_map()
        validation_errors = validate_issuer(settings, identity["cnpj"])
        simulations = []
        for sale_id in sale_ids:
            sale = db.session.get(PharmacySale, sale_id)
            if not sale:
                raise ValueError(f"Venda {sale_id} nao encontrada.")
            if sale.status == "cancelled":
                raise ValueError(f"O pedido {sale.code} esta cancelado e nao pode ser faturado.")
            for item in sale.items.order_by(PharmacySaleItem.id.asc()).all():
                validation_errors.extend(validate_product(item.product, settings.get("FISCAL_CRT", ""), document_model))
            if validation_errors:
                unique_errors = list(dict.fromkeys(validation_errors))
                raise ValueError("Cadastro fiscal incompleto: " + " | ".join(unique_errors))
            result = build_signed_simulation(_sale_fiscal_payload(sale), document_model, identity=identity)
            simulation = FiscalSimulation(
                code=result["code"],
                sale_id=sale.id,
                document_model=result["document_model"],
                environment="simulation",
                status=result["status"],
                issuer_cnpj=result["issuer_cnpj"],
                total_amount=sale.total_amount,
                certificate_serial=result["certificate_serial"],
                certificate_fingerprint=result["certificate_fingerprint"],
                xml_content=result["xml"],
            )
            db.session.add(simulation)
            simulations.append(simulation)
        db.session.commit()
    except (RuntimeError, ValueError) as exc:
        db.session.rollback()
        abort(400, str(exc))

    return jsonify(
        {
            "ok": True,
            "count": len(simulations),
            "transmitted": False,
            "warning": "Simulacao local concluida. Nenhum documento foi transmitido a SEFAZ.",
            "items": [_serialize_fiscal_simulation(item) for item in simulations],
        }
    )


@bp.route("/api/fiscal/simulations/<int:simulation_id>/xml")
def api_fiscal_simulation_xml(simulation_id):
    simulation = db.session.get(FiscalSimulation, simulation_id) or abort(404, "Simulacao fiscal nao encontrada.")
    response = Response(simulation.xml_content, mimetype="application/xml")
    response.headers["Content-Disposition"] = f'attachment; filename="{simulation.code}.xml"'
    return response


@bp.route("/api/fiscal/simulations/<int:simulation_id>/pdf")
def api_fiscal_simulation_pdf(simulation_id):
    simulation = db.session.get(FiscalSimulation, simulation_id) or abort(404, "Simulacao fiscal nao encontrada.")
    format_name = (request.args.get("format") or "a4").strip().lower()
    try:
        document = build_fiscal_pdf(simulation, _setting_map(), format_name)
    except ValueError as exc:
        abort(400, str(exc))
    return send_file(
        document, mimetype="application/pdf", as_attachment=False,
        download_name=f"{simulation.code}-{format_name}.pdf",
    )


@bp.route("/api/orders/<int:sale_id>/pdf")
def api_order_pdf(sale_id):
    sale = db.session.get(PharmacySale, sale_id) or abort(404, "Pedido nao encontrado.")
    format_name = (request.args.get("format") or "a4").strip().lower()
    try:
        document = build_order_pdf(sale, format_name)
    except ValueError as exc:
        abort(400, str(exc))
    return send_file(
        document, mimetype="application/pdf", as_attachment=False,
        download_name=f"{sale.code}-{format_name}.pdf",
    )


@bp.route("/api/payments/process", methods=["POST"])
def api_payments():
    payload = request.get_json(force=True)
    sale = db.session.get(PharmacySale, payload.get("sale_id")) or abort(404, "Venda nao encontrada.")
    try:
        payment = _record_sale_payment(sale, payload)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        abort(400, str(exc))
    return jsonify({"ok": True, "payment": _serialize_payment(payment), "sale": _serialize_sale(sale)})


@bp.route("/api/orders/external", methods=["POST"])
def api_external_orders():
    payload = request.get_json(force=True)
    payload["source_channel"] = (payload.get("platform") or payload.get("source_channel") or "integracao").strip().lower()
    return api_sales()


@bp.route("/api/settings", methods=["POST"])
def api_settings():
    payload = request.get_json(force=True)
    settings = payload.get("settings") or {}
    if not isinstance(settings, dict):
        abort(400, "Formato invalido.")
    for key, value in settings.items():
        _set_setting(key, value)
    db.session.commit()
    return jsonify({"ok": True, "saved": len(settings)})


@bp.route("/api/purchases", methods=["POST"])
def api_purchases():
    payload = request.get_json(force=True)
    supplier = db.session.get(PharmacySupplier, payload.get("supplier_id")) or abort(400, "Fornecedor obrigatorio.")
    items = payload.get("items") or []
    if not items:
        abort(400, "Informe ao menos um item da compra.")
    purchase_type = (payload.get("purchase_type") or "restock").strip().lower()
    if purchase_type not in {"restock", "free"}:
        abort(400, "Tipo de compra invalido.")
    purchase = PurchaseOrder(
        code=(payload.get("code") or f"PC-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid4().hex[:5].upper()}").strip(),
        supplier_id=supplier.id,
        purchase_type=purchase_type,
        status=(payload.get("status") or "received").strip().lower(),
        order_date=_parse_date(payload.get("order_date"), "Data da compra"),
        expected_date=_parse_date(payload.get("expected_date"), "Data prevista") if payload.get("expected_date") else None,
        notes=(payload.get("notes") or "").strip(),
    )
    db.session.add(purchase)
    db.session.flush()
    total_amount = Decimal("0")
    try:
        for raw_item in items:
            item_type = (raw_item.get("item_type") or purchase_type).strip().lower()
            if item_type not in {"restock", "free"}:
                raise ValueError("Tipo de item de compra invalido.")

            product = None
            free_item_name = (raw_item.get("free_item_name") or raw_item.get("name") or "").strip()
            if raw_item.get("product_id"):
                product = db.session.get(PharmacyProduct, int(raw_item["product_id"]))
            elif raw_item.get("sku"):
                product = PharmacyProduct.query.filter(func.lower(PharmacyProduct.sku) == str(raw_item["sku"]).strip().lower()).first()

            if item_type == "restock" and not product:
                new_product_name = (raw_item.get("new_product_name") or "").strip()
                new_product_sku = (raw_item.get("new_product_sku") or "").strip()
                if new_product_name and new_product_sku:
                    existing_product = PharmacyProduct.query.filter(func.lower(PharmacyProduct.sku) == new_product_sku.lower()).first()
                    if existing_product:
                        product = existing_product
                    else:
                        category_id = raw_item.get("category_id") or payload.get("default_category_id") or None
                        category = db.session.get(PharmacyCategory, category_id) if category_id else None
                        new_cost = _to_decimal(raw_item.get("unit_cost"), f"custo de {new_product_name}")
                        new_sale_price = _to_decimal(raw_item.get("sale_price"), f"venda de {new_product_name}", default="0")
                        if new_sale_price <= 0 and category and Decimal(category.suggested_profit_margin or 0) > 0:
                            new_sale_price = (new_cost * (Decimal("1") + (Decimal(category.suggested_profit_margin or 0) / Decimal("100")))).quantize(Decimal("0.01"))
                        product = PharmacyProduct(
                            sku=new_product_sku,
                            name=new_product_name,
                            category_id=category_id,
                            supplier_id=supplier.id,
                            unit=(raw_item.get("unit") or "un").strip() or "un",
                            cost_price=new_cost,
                            sale_price=new_sale_price,
                            minimum_stock=_to_decimal(raw_item.get("minimum_stock"), "estoque minimo"),
                        )
                        db.session.add(product)
                        db.session.flush()
                else:
                    raise ValueError("Na reposicao de estoque, selecione um produto ou informe os dados para cadastrar.")

            if item_type == "free" and not product and not free_item_name:
                raise ValueError("Na compra livre, informe o nome do item.")

            item_label = product.name if product else free_item_name
            quantity = _to_decimal(raw_item.get("quantity"), f"quantidade de {item_label}")
            unit_cost = _to_decimal(raw_item.get("unit_cost"), f"custo de {item_label}", default=str(product.cost_price if product else "0"))
            sale_price = _to_decimal(raw_item.get("sale_price"), f"preco de venda de {item_label}", default=str(product.sale_price if product else "0"))
            if quantity <= 0:
                raise ValueError(f"Quantidade invalida para {item_label}.")
            line_total = (quantity * unit_cost).quantize(Decimal("0.01"))
            expiration_date = _parse_date(raw_item.get("expiration_date"), "Validade do item") if raw_item.get("expiration_date") else None
            db.session.add(
                PurchaseOrderItem(
                    purchase_id=purchase.id,
                    product_id=product.id if product else None,
                    item_type=item_type,
                    free_item_name="" if product else free_item_name,
                    quantity=quantity,
                    unit_cost=unit_cost,
                    total_amount=line_total,
                    lot_code=(raw_item.get("lot_code") or "").strip(),
                    expiration_date=expiration_date,
                    location=(raw_item.get("location") or "").strip(),
                    sale_price=sale_price,
                )
            )
            total_amount += line_total
            if purchase.status in {"received", "completed"} and product:
                lot_code = (raw_item.get("lot_code") or f"{product.sku}-{datetime.utcnow():%m%d%H%M}").strip()
                created_lot = PharmacyLot(
                    product_id=product.id,
                    supplier_id=supplier.id,
                    lot_code=lot_code,
                    expiration_date=expiration_date or (date.today() + timedelta(days=365)),
                    received_at=purchase.order_date,
                    quantity_received=quantity,
                    quantity_available=quantity,
                    purchase_price=unit_cost,
                    location=(raw_item.get("location") or "").strip(),
                )
                db.session.add(created_lot)
                db.session.flush()
                _log_stock_movement(
                    movement_type="purchase",
                    product=product,
                    lot=created_lot,
                    quantity=quantity,
                    reference_code=purchase.code,
                    notes=f"Entrada por compra {purchase.code}.",
                )
                product.cost_price = unit_cost
                category = product.category
                if sale_price > 0:
                    product.sale_price = sale_price
                elif category and Decimal(category.suggested_profit_margin or 0) > 0:
                    suggested = (unit_cost * (Decimal("1") + (Decimal(category.suggested_profit_margin or 0) / Decimal("100")))).quantize(Decimal("0.01"))
                    product.sale_price = suggested
        purchase.total_amount = total_amount
        db.session.add(
            FinancialEntry(
                entry_type="payable",
                category="Compra",
                description=f"Pagamento da compra {purchase.code}",
                counterparty=supplier.name,
                amount=total_amount,
                status="open",
                due_date=purchase.expected_date or purchase.order_date,
                source_ref=purchase.code,
                notes=purchase.notes,
            )
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        abort(400, str(exc))
    return jsonify({"ok": True, "purchase": _serialize_purchase(purchase)})


@bp.route("/api/financial/entries", methods=["POST"])
def api_financial_entries():
    payload = request.get_json(force=True)
    entry_type = (payload.get("entry_type") or "").strip().lower()
    if entry_type not in {"payable", "receivable"}:
        abort(400, "Tipo financeiro invalido.")
    entry = FinancialEntry(
        entry_type=entry_type,
        category=(payload.get("category") or "").strip(),
        description=(payload.get("description") or "").strip(),
        counterparty=(payload.get("counterparty") or "").strip(),
        amount=_to_decimal(payload.get("amount"), "valor"),
        status=(payload.get("status") or "open").strip().lower(),
        due_date=_parse_date(payload.get("due_date"), "Vencimento"),
        source_ref=(payload.get("source_ref") or "").strip(),
        notes=(payload.get("notes") or "").strip(),
    )
    if not entry.description:
        abort(400, "Descricao obrigatoria.")
    if entry.status == "paid":
        entry.paid_at = datetime.utcnow()
    db.session.add(entry)
    db.session.commit()
    return jsonify({"ok": True, "entry": _serialize_financial_entry(entry)})


@bp.route("/api/financial/entries/<int:entry_id>/settle", methods=["POST"])
def api_financial_settle(entry_id):
    entry = db.session.get(FinancialEntry, entry_id) or abort(404, "Lancamento nao encontrado.")
    payload = request.get_json(force=True, silent=True) or {}
    entry.status = (payload.get("status") or "paid").strip().lower()
    entry.paid_at = datetime.utcnow()
    if entry.status not in {"paid", "partial"}:
        entry.status = "paid"
    db.session.commit()
    return jsonify({"ok": True, "entry": _serialize_financial_entry(entry)})


@bp.route("/api/cash/open", methods=["POST"])
def api_cash_open():
    if _current_cash_session():
        abort(400, "Ja existe um caixa aberto.")
    payload = request.get_json(force=True, silent=True) or {}
    session = CashSession(
        opened_at=datetime.utcnow(),
        status="open",
        opening_amount=_to_decimal(payload.get("opening_amount"), "abertura"),
        expected_amount=_to_decimal(payload.get("opening_amount"), "abertura"),
        notes=(payload.get("notes") or "").strip(),
    )
    db.session.add(session)
    db.session.commit()
    return jsonify({"ok": True, "cash_session_id": session.id})


@bp.route("/api/cash/close", methods=["POST"])
def api_cash_close():
    session = _current_cash_session() or abort(400, "Nao existe caixa aberto.")
    payload = request.get_json(force=True, silent=True) or {}
    closing_amount = _to_decimal(payload.get("closing_amount"), "fechamento")
    session.closed_at = datetime.utcnow()
    session.status = "closed"
    session.closing_amount = closing_amount
    session.expected_amount = Decimal(session.opening_amount or 0) + _cash_received_total(session.id)
    session.difference_amount = closing_amount - Decimal(session.expected_amount or 0)
    session.notes = (payload.get("notes") or session.notes or "").strip()
    db.session.commit()
    return jsonify({"ok": True, "difference_amount": float(session.difference_amount or 0)})


@bp.route("/api/cash/movements", methods=["POST"])
def api_cash_movements():
    session = _current_cash_session() or abort(400, "Abra o caixa antes de registrar movimentos.")
    payload = request.get_json(force=True)
    direction = (payload.get("direction") or "").strip().lower()
    if direction not in {"in", "out"}:
        abort(400, "Movimento deve ser entrada ou saida.")
    amount = _to_decimal(payload.get("amount"), "valor")
    description = (payload.get("description") or "").strip()
    if amount <= 0 or not description:
        abort(400, "Descricao e valor maior que zero sao obrigatorios.")
    movement = CashMovement(
        cash_session_id=session.id, direction=direction, category=(payload.get("category") or "").strip(),
        description=description, amount=amount,
    )
    db.session.add(movement)
    db.session.flush()
    session.expected_amount = Decimal(session.opening_amount or 0) + _cash_received_total(session.id)
    db.session.commit()
    return jsonify({"ok": True, "movement": _serialize_cash_movement(movement), "expected_amount": float(session.expected_amount or 0)})


@bp.route("/api/stock/adjustments", methods=["POST"])
def api_stock_adjustment():
    payload = request.get_json(force=True)
    lot = db.session.get(PharmacyLot, payload.get("lot_id")) or abort(400, "Lote obrigatorio.")
    product = lot.product
    adjustment_type = (payload.get("adjustment_type") or "set").strip().lower()
    quantity = _to_decimal(payload.get("quantity"), "quantidade")
    previous_balance = Decimal(lot.quantity_available or 0)
    if adjustment_type == "increase":
        lot.quantity_available = previous_balance + quantity
        movement_qty = quantity
    elif adjustment_type == "decrease":
        lot.quantity_available = previous_balance - quantity
        movement_qty = -quantity
    else:
        lot.quantity_available = quantity
        movement_qty = quantity - previous_balance
    if Decimal(lot.quantity_available or 0) < 0:
        abort(400, "Saldo do lote nao pode ficar negativo.")
    _log_stock_movement(
        movement_type="adjustment",
        product=product,
        lot=lot,
        quantity=movement_qty,
        reference_code=(payload.get("reference_code") or f"AJ-{lot.id}").strip(),
        notes=(payload.get("notes") or "Ajuste manual de estoque.").strip(),
    )
    db.session.commit()
    return jsonify({"ok": True, "lot": _serialize_lot(lot)})


@bp.route("/api/stock/counts", methods=["POST"])
def api_stock_count():
    payload = request.get_json(force=True)
    items = payload.get("items") or []
    if not items:
        abort(400, "Informe ao menos um item para contagem.")
    count = InventoryCount(
        code=(payload.get("code") or f"INV-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid4().hex[:5].upper()}").strip(),
        status=(payload.get("status") or "completed").strip().lower(),
        count_date=_parse_date(payload.get("count_date"), "Data da contagem"),
        notes=(payload.get("notes") or "").strip(),
    )
    db.session.add(count)
    db.session.flush()
    try:
        for raw_item in items:
            lot = db.session.get(PharmacyLot, raw_item.get("lot_id")) or abort(400, "Lote obrigatorio em cada item da contagem.")
            product = lot.product
            expected_quantity = Decimal(lot.quantity_available or 0)
            counted_quantity = _to_decimal(raw_item.get("counted_quantity"), f"contagem de {product.name}")
            difference_quantity = counted_quantity - expected_quantity
            db.session.add(
                InventoryCountItem(
                    inventory_count_id=count.id,
                    product_id=product.id,
                    lot_id=lot.id,
                    expected_quantity=expected_quantity,
                    counted_quantity=counted_quantity,
                    difference_quantity=difference_quantity,
                    notes=(raw_item.get("notes") or "").strip(),
                )
            )
            lot.quantity_available = counted_quantity
            if difference_quantity != 0:
                _log_stock_movement(
                    movement_type="count",
                    product=product,
                    lot=lot,
                    quantity=difference_quantity,
                    reference_code=count.code,
                    notes=f"Contagem de estoque {count.code}.",
                )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        abort(400, str(exc))
    return jsonify({"ok": True, "count": _serialize_inventory_count(count)})


@bp.route("/api/workflow/tickets", methods=["POST"])
def api_workflow_tickets():
    payload = request.get_json(force=True)
    stage = db.session.get(WorkflowStage, payload.get("stage_id")) if payload.get("stage_id") else _default_stage()
    if not stage:
        abort(400, "Etapa do workflow obrigatoria.")
    title = (payload.get("title") or "").strip()
    if not title:
        abort(400, "Titulo do card obrigatorio.")
    ticket = WorkflowTicket(
        code=(payload.get("code") or f"WK-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid4().hex[:5].upper()}").strip(),
        title=title,
        customer_name=(payload.get("customer_name") or "").strip(),
        customer_phone=("".join(ch for ch in str(payload.get("customer_phone") or "") if ch.isdigit())),
        source_channel=(payload.get("source_channel") or "manual").strip().lower(),
        priority=(payload.get("priority") or "normal").strip().lower(),
        status="open",
        stage_id=stage.id,
        sale_id=payload.get("sale_id") or None,
        description=(payload.get("description") or "").strip(),
        assigned_to=(payload.get("assigned_to") or "").strip(),
    )
    db.session.add(ticket)
    db.session.flush()
    if ticket.description:
        db.session.add(
            InternalChatMessage(
                ticket_id=ticket.id,
                author_name="Sistema",
                message=f"Card aberto: {ticket.description}",
            )
        )
    db.session.commit()
    return jsonify({"ok": True, "ticket": _serialize_ticket(ticket)})


@bp.route("/api/workflow/tickets/<int:ticket_id>", methods=["PATCH"])
def api_workflow_ticket_update(ticket_id):
    ticket = db.session.get(WorkflowTicket, ticket_id) or abort(404, "Card nao encontrado.")
    payload = request.get_json(force=True)
    if "stage_id" in payload:
        stage = db.session.get(WorkflowStage, payload.get("stage_id"))
        if not stage:
            abort(400, "Etapa invalida.")
        ticket.stage_id = stage.id
        ticket.status = "closed" if stage.is_closed else "open"
    if "assigned_to" in payload:
        ticket.assigned_to = (payload.get("assigned_to") or "").strip()
    if "priority" in payload:
        ticket.priority = (payload.get("priority") or "normal").strip().lower()
    db.session.commit()
    return jsonify({"ok": True, "ticket": _serialize_ticket(ticket)})


@bp.route("/api/workflow/tickets/<int:ticket_id>/messages", methods=["POST"])
def api_workflow_ticket_message(ticket_id):
    ticket = db.session.get(WorkflowTicket, ticket_id) or abort(404, "Card nao encontrado.")
    payload = request.get_json(force=True)
    message = (payload.get("message") or "").strip()
    if not message:
        abort(400, "Mensagem obrigatoria.")
    row = InternalChatMessage(
        ticket_id=ticket.id,
        author_name=(payload.get("author_name") or "Equipe").strip() or "Equipe",
        message=message,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "message": _serialize_ticket_message(row), "ticket": _serialize_ticket(ticket)})


@bp.route("/api/workflow/stages", methods=["GET", "POST"])
def api_workflow_stage_create():
    if request.method == "GET":
        stages = WorkflowStage.query.order_by(WorkflowStage.order_index.asc(), WorkflowStage.id.asc()).all()
        return jsonify({"ok": True, "items": [_serialize_workflow_stage(stage) for stage in stages]})
    payload = request.get_json(force=True)
    name = (payload.get("name") or "").strip()
    if not name:
        abort(400, "Nome da etapa obrigatorio.")
    stage = WorkflowStage(
        name=name,
        color=(payload.get("color") or "#2d8a4d").strip(),
        order_index=int(payload.get("order_index") or 0),
        is_default=_to_bool(payload.get("is_default")),
        is_closed=_to_bool(payload.get("is_closed")),
    )
    if stage.is_default:
        for existing in WorkflowStage.query.all():
            existing.is_default = False
    db.session.add(stage)
    db.session.commit()
    return jsonify({"ok": True, "stage": _serialize_workflow_stage(stage)})


@bp.route("/api/workflow/stages/<int:stage_id>", methods=["PATCH"])
def api_workflow_stage_update(stage_id):
    stage = db.session.get(WorkflowStage, stage_id) or abort(404, "Etapa nao encontrada.")
    payload = request.get_json(force=True)
    if "name" in payload:
        stage.name = (payload.get("name") or "").strip() or stage.name
    if "color" in payload:
        stage.color = (payload.get("color") or "").strip() or stage.color
    if "order_index" in payload:
        stage.order_index = int(payload.get("order_index") or 0)
    if "is_closed" in payload:
        stage.is_closed = _to_bool(payload.get("is_closed"))
    if "is_default" in payload:
        make_default = _to_bool(payload.get("is_default"))
        if make_default:
            for existing in WorkflowStage.query.all():
                existing.is_default = existing.id == stage.id
        else:
            stage.is_default = False
    db.session.commit()
    return jsonify({"ok": True, "stage": _serialize_workflow_stage(stage)})
