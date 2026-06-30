from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import os
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from flask import Blueprint, Response, abort, jsonify, render_template, request
from sqlalchemy import func
from werkzeug.exceptions import HTTPException

from .extensions import db
from .models import (
    CashSession,
    IntegrationSetting,
    InventoryCount,
    InventoryCountItem,
    FinancialEntry,
    InternalChatMessage,
    PharmacyCategory,
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
        cert_hosts.append(public_base_url)
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
        "category_name": product.category.name if product.category else "",
        "category_id": product.category_id,
        "supplier_name": product.supplier.name if product.supplier else "",
        "stock": float(_product_stock(product.id)),
        "minimum_stock": float(product.minimum_stock or 0),
        "sale_price": float(product.sale_price or 0),
        "cost_price": float(product.cost_price or 0),
        "minimum_profit_margin": float(category.minimum_profit_margin or 0) if category else 0.0,
        "suggested_profit_margin": float(category.suggested_profit_margin or 0) if category else 0.0,
    }


def _serialize_lot(lot):
    return {
        "id": lot.id,
        "product_id": lot.product_id,
        "product_name": lot.product.name if lot.product else "",
        "lot_code": lot.lot_code,
        "expiration_date": lot.expiration_date.isoformat(),
        "quantity_available": float(lot.quantity_available or 0),
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
    return {
        "id": sale.id,
        "code": sale.code,
        "customer_name": sale.customer_name,
        "source_channel": sale.source_channel,
        "status": sale.status,
        "total_amount": float(sale.total_amount or 0),
        "items": [
            {
                "product_name": item.product.name if item.product else "",
                "lot_code": item.lot.lot_code if item.lot else "",
                "quantity": float(item.quantity or 0),
                "total_amount": float(item.total_amount or 0),
            }
            for item in sale.items.order_by(PharmacySaleItem.id.asc()).all()
        ],
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
        "method": payment.method,
        "provider": payment.provider,
        "amount": float(payment.amount or 0),
        "status": payment.status,
        "transaction_reference": payment.transaction_reference,
        "paid_at": payment.paid_at.isoformat() + "Z" if payment.paid_at else "",
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


def _cash_received_total():
    total = db.session.query(func.coalesce(func.sum(PharmacyPayment.amount), 0)).filter(
        PharmacyPayment.status.in_(["paid", "authorized"]),
        PharmacyPayment.method.in_(["cash", "debit_card", "credit_card", "card_machine", "pix"]),
    ).scalar()
    return Decimal(total or 0)


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
    sales_today = PharmacySale.query.filter(func.date(PharmacySale.created_at) == today.isoformat()).all()
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
    payment_method_totals = {}
    for payment in PharmacyPayment.query.all():
        key = payment.method or "outros"
        payment_method_totals[key] = payment_method_totals.get(key, 0.0) + float(payment.amount or 0)
    paid_entries = FinancialEntry.query.filter_by(status="paid").order_by(FinancialEntry.updated_at.desc(), FinancialEntry.id.desc()).limit(20).all()
    unpaid_entries = FinancialEntry.query.filter(FinancialEntry.status.in_(["open", "partial"])).order_by(FinancialEntry.due_date.asc(), FinancialEntry.id.desc()).limit(20).all()
    stages = WorkflowStage.query.order_by(WorkflowStage.order_index.asc(), WorkflowStage.id.asc()).all()
    tickets = WorkflowTicket.query.order_by(WorkflowTicket.updated_at.desc(), WorkflowTicket.id.desc()).all()
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
        "products": [_serialize_product(product) for product in products],
        "all_lots": [_serialize_lot(lot) for lot in lots],
        "expiring_lots": [_serialize_lot(lot) for lot in expiring_lots],
        "low_stock_products": [_serialize_product(product) for product in low_stock],
        "no_stock_products": [_serialize_product(product) for product in no_stock],
        "recent_sales": [_serialize_sale(sale) for sale in PharmacySale.query.order_by(PharmacySale.created_at.desc()).limit(8).all()],
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
    menu_sections = [
        {"id": "inicio", "title": "Inicio", "description": "Visao geral e indicadores"},
        {"id": "workflow", "title": "Workflow", "description": "Kanban, WhatsApp e chat interno"},
        {"id": "cadastros", "title": "Cadastros", "description": "Produtos, categorias e fornecedores"},
        {"id": "lancamentos", "title": "Lancamentos", "description": "Lotes, vendas, compras e financeiro"},
        {"id": "relatorios", "title": "Relatorios", "description": "Estoque, vencimentos, caixa e performance"},
        {"id": "configuracao", "title": "Configuracao", "description": "Provedores e canais de integracao"},
    ]
    return render_template(
        "index.html",
        title="NanoStore",
        summary=summary,
        categories=PharmacyCategory.query.order_by(PharmacyCategory.name.asc()).all(),
        suppliers=PharmacySupplier.query.order_by(PharmacySupplier.name.asc()).all(),
        settings_map=_setting_map(),
        https_runtime=_https_runtime_config(),
        menu_sections=menu_sections,
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
    http_base = f"http://{current_host}:{https_runtime['http_port']}"
    https_base = f"https://{current_host}:{https_runtime['https_port']}"
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


@bp.route("/api/products", methods=["GET", "POST"])
def api_products():
    if request.method == "GET":
        products = PharmacyProduct.query.order_by(PharmacyProduct.name.asc()).all()
        return jsonify({"ok": True, "items": [_serialize_product(product) for product in products]})
    payload = request.get_json(force=True)
    name = (payload.get("name") or "").strip()
    sku = (payload.get("sku") or "").strip()
    if not name or not sku:
        abort(400, "Nome e SKU sao obrigatorios.")
    category = db.session.get(PharmacyCategory, payload.get("category_id")) if payload.get("category_id") else None
    cost_price = _to_decimal(payload.get("cost_price"), "preco de custo")
    sale_price = _to_decimal(payload.get("sale_price"), "preco de venda")
    if sale_price <= 0 and category and Decimal(category.suggested_profit_margin or 0) > 0:
        sale_price = (cost_price * (Decimal("1") + (Decimal(category.suggested_profit_margin or 0) / Decimal("100")))).quantize(Decimal("0.01"))
    product = PharmacyProduct(
        sku=sku,
        name=name,
        barcode=((payload.get("barcode") or "").strip() or None),
        brand=(payload.get("brand") or "").strip(),
        active_ingredient=(payload.get("active_ingredient") or "").strip(),
        unit=(payload.get("unit") or "un").strip() or "un",
        sale_price=sale_price,
        cost_price=cost_price,
        minimum_stock=_to_decimal(payload.get("minimum_stock"), "estoque minimo"),
        requires_prescription=_to_bool(payload.get("requires_prescription")),
        is_controlled=_to_bool(payload.get("is_controlled")),
        is_active=not str(payload.get("is_active", "true")).strip().lower() in {"0", "false", "off", "nao"},
        category_id=category.id if category else None,
        supplier_id=payload.get("supplier_id") or None,
    )
    db.session.add(product)
    db.session.commit()
    return jsonify({"ok": True, "product": _serialize_product(product)})


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
    customer_name = (payload.get("customer_name") or "").strip()
    if not customer_name:
        abort(400, "Cliente obrigatorio.")
    sale = PharmacySale(
        code=(payload.get("code") or f"NS-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid4().hex[:5].upper()}").strip(),
        customer_name=customer_name,
        customer_phone=("".join(ch for ch in str(payload.get("customer_phone") or "") if ch.isdigit())),
        source_channel=(payload.get("source_channel") or "balcao").strip().lower(),
        status="open",
        notes=(payload.get("notes") or "").strip(),
        external_order_id=(payload.get("external_order_id") or "").strip(),
    )
    db.session.add(sale)
    db.session.flush()

    subtotal = Decimal("0")
    discount_total = Decimal("0")
    try:
        for raw_item in items:
            product = None
            if raw_item.get("product_id"):
                product = db.session.get(PharmacyProduct, int(raw_item["product_id"]))
            elif raw_item.get("sku"):
                product = PharmacyProduct.query.filter(func.lower(PharmacyProduct.sku) == str(raw_item["sku"]).strip().lower()).first()
            if not product:
                raise ValueError("Produto nao encontrado em um dos itens.")
            quantity = _to_decimal(raw_item.get("quantity"), f"quantidade de {product.name}")
            unit_price = _to_decimal(raw_item.get("unit_price"), f"preco de {product.name}", default=str(product.sale_price or "0"))
            line_discount = _to_decimal(raw_item.get("discount_amount"), f"desconto de {product.name}")
            floor_price = _margin_floor_price(product.cost_price or 0, product.category)
            final_unit_price = (unit_price - (line_discount / quantity)).quantize(Decimal("0.01")) if quantity > 0 else unit_price
            if final_unit_price < floor_price:
                raise ValueError(
                    f"Desconto maior que a margem permitida para {product.name}. "
                    f"Preco minimo: R$ {floor_price:.2f}."
                )
            selections = _select_lots(product.id, quantity)
            for lot, consume in selections:
                proportional_discount = (line_discount * consume / quantity).quantize(Decimal("0.01")) if line_discount > 0 else Decimal("0")
                line_total = (unit_price * consume - proportional_discount).quantize(Decimal("0.01"))
                lot.quantity_available = Decimal(lot.quantity_available or 0) - consume
                db.session.add(
                    PharmacySaleItem(
                        sale_id=sale.id,
                        product_id=product.id,
                        lot_id=lot.id,
                        quantity=consume,
                        unit_price=unit_price,
                        discount_amount=proportional_discount,
                        total_amount=line_total,
                    )
                )
                _log_stock_movement(
                    movement_type="sale",
                    product=product,
                    lot=lot,
                    quantity=-consume,
                    reference_code=sale.code,
                    notes=f"Saida por venda {sale.code}.",
                )
                subtotal += (unit_price * consume).quantize(Decimal("0.01"))
                discount_total += proportional_discount
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
        _ensure_workflow_ticket_for_sale(sale)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        abort(400, str(exc))
    return jsonify({"ok": True, "sale": _serialize_sale(sale)})


@bp.route("/api/payments/process", methods=["POST"])
def api_payments():
    payload = request.get_json(force=True)
    sale = db.session.get(PharmacySale, payload.get("sale_id")) or abort(404, "Venda nao encontrada.")
    method = (payload.get("method") or "").strip().lower()
    if method not in {"pix", "card_machine", "credit_card", "debit_card", "cash"}:
        abort(400, "Metodo invalido.")
    amount = _to_decimal(payload.get("amount"), "valor", default=str(sale.total_amount or "0"))
    settings = _setting_map()
    provider = (payload.get("provider") or "").strip() or (
        settings.get("PHARMACY_PIX_PROVIDER", "") if method == "pix" else settings.get("PHARMACY_CARD_PROVIDER", "")
    )
    reference = f"{method.upper()}-{uuid4().hex[:10].upper()}"
    payment = PharmacyPayment(
        sale_id=sale.id,
        method=method,
        provider=provider,
        amount=amount,
        status="pending" if method == "pix" else "authorized",
        transaction_reference=reference,
        pix_qr_code=f"PIX|{sale.code}|{amount:.2f}|{reference}" if method == "pix" else "",
        pix_copy_paste=f"000201{sale.code}{reference}" if method == "pix" else "",
        card_brand=(payload.get("card_brand") or "").strip(),
        installments=max(1, int(payload.get("installments") or 1)),
        paid_at=datetime.utcnow() if method == "cash" else None,
    )
    db.session.add(payment)
    if method == "cash":
        payment.status = "paid"
        sale.status = "paid"
    elif method != "pix":
        sale.status = "partially_paid"
    receivable_entry = FinancialEntry.query.filter_by(source_ref=sale.code, entry_type="receivable").order_by(FinancialEntry.id.desc()).first()
    if receivable_entry:
        if payment.status == "paid":
            receivable_entry.status = "paid"
            receivable_entry.paid_at = datetime.utcnow()
        elif payment.status == "authorized":
            receivable_entry.status = "partial"
    cash_session = _current_cash_session()
    if cash_session and payment.status in {"paid", "authorized"}:
        cash_session.expected_amount = Decimal(cash_session.expected_amount or 0) + amount
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "payment": {
                "method": payment.method,
                "provider": payment.provider,
                "amount": float(payment.amount or 0),
                "status": payment.status,
                "transaction_reference": payment.transaction_reference,
                "pix_qr_code": payment.pix_qr_code,
                "pix_copy_paste": payment.pix_copy_paste,
            }
        }
    )


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
    if Decimal(session.expected_amount or 0) <= 0:
        session.expected_amount = Decimal(session.opening_amount or 0) + _cash_received_total()
    session.difference_amount = closing_amount - Decimal(session.expected_amount or 0)
    session.notes = (payload.get("notes") or session.notes or "").strip()
    db.session.commit()
    return jsonify({"ok": True, "difference_amount": float(session.difference_amount or 0)})


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
