from datetime import datetime

from .extensions import db


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PharmacyCategory(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    description = db.Column(db.Text, default="", nullable=False)
    minimum_profit_margin = db.Column(db.Numeric(8, 2), default=0, nullable=False)
    suggested_profit_margin = db.Column(db.Numeric(8, 2), default=0, nullable=False)


class PharmacySupplier(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False, unique=True)
    document = db.Column(db.String(40), default="", nullable=False)
    phone = db.Column(db.String(40), default="", nullable=False)
    email = db.Column(db.String(255), default="", nullable=False)


class PharmacyProduct(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(60), nullable=False, unique=True, index=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    barcode = db.Column(db.String(60), nullable=True, unique=True)
    brand = db.Column(db.String(120), default="", nullable=False)
    active_ingredient = db.Column(db.String(160), default="", nullable=False)
    unit = db.Column(db.String(20), default="un", nullable=False)
    sale_price = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    cost_price = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    minimum_stock = db.Column(db.Numeric(12, 3), default=0, nullable=False)
    requires_prescription = db.Column(db.Boolean, default=False, nullable=False)
    is_controlled = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("pharmacy_category.id"))
    supplier_id = db.Column(db.Integer, db.ForeignKey("pharmacy_supplier.id"))

    category = db.relationship("PharmacyCategory")
    supplier = db.relationship("PharmacySupplier")


class PharmacyLot(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("pharmacy_product.id"), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("pharmacy_supplier.id"))
    lot_code = db.Column(db.String(80), nullable=False, index=True)
    expiration_date = db.Column(db.Date, nullable=False, index=True)
    received_at = db.Column(db.Date, nullable=False)
    quantity_received = db.Column(db.Numeric(12, 3), default=0, nullable=False)
    quantity_available = db.Column(db.Numeric(12, 3), default=0, nullable=False)
    purchase_price = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    location = db.Column(db.String(120), default="", nullable=False)

    product = db.relationship("PharmacyProduct", backref=db.backref("lots", lazy="dynamic"))
    supplier = db.relationship("PharmacySupplier")


class PharmacySale(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), nullable=False, unique=True, index=True)
    customer_name = db.Column(db.String(140), nullable=False)
    customer_phone = db.Column(db.String(40), default="", nullable=False)
    source_channel = db.Column(db.String(60), default="balcao", nullable=False, index=True)
    status = db.Column(db.String(40), default="open", nullable=False, index=True)
    subtotal_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    discount_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    notes = db.Column(db.Text, default="", nullable=False)
    external_order_id = db.Column(db.String(120), default="", nullable=False, index=True)


class PharmacySaleItem(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("pharmacy_sale.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("pharmacy_product.id"), nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey("pharmacy_lot.id"), nullable=False)
    quantity = db.Column(db.Numeric(12, 3), default=0, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    discount_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    sale = db.relationship("PharmacySale", backref=db.backref("items", lazy="dynamic"))
    product = db.relationship("PharmacyProduct")
    lot = db.relationship("PharmacyLot")


class PharmacyPayment(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("pharmacy_sale.id"), nullable=False, index=True)
    method = db.Column(db.String(40), nullable=False, index=True)
    provider = db.Column(db.String(80), default="", nullable=False)
    amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    status = db.Column(db.String(40), default="pending", nullable=False, index=True)
    transaction_reference = db.Column(db.String(160), default="", nullable=False, index=True)
    pix_qr_code = db.Column(db.Text, default="", nullable=False)
    pix_copy_paste = db.Column(db.Text, default="", nullable=False)
    card_brand = db.Column(db.String(60), default="", nullable=False)
    installments = db.Column(db.Integer, default=1, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)

    sale = db.relationship("PharmacySale", backref=db.backref("payments", lazy="dynamic"))


class PurchaseOrder(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), nullable=False, unique=True, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("pharmacy_supplier.id"), nullable=False, index=True)
    purchase_type = db.Column(db.String(20), default="restock", nullable=False, index=True)
    status = db.Column(db.String(40), default="open", nullable=False, index=True)
    order_date = db.Column(db.Date, nullable=False)
    expected_date = db.Column(db.Date, nullable=True)
    total_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    notes = db.Column(db.Text, default="", nullable=False)

    supplier = db.relationship("PharmacySupplier", backref=db.backref("purchase_orders", lazy="dynamic"))


class PurchaseOrderItem(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchase_order.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("pharmacy_product.id"), nullable=True)
    item_type = db.Column(db.String(20), default="restock", nullable=False, index=True)
    free_item_name = db.Column(db.String(160), default="", nullable=False)
    quantity = db.Column(db.Numeric(12, 3), default=0, nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    lot_code = db.Column(db.String(80), default="", nullable=False)
    expiration_date = db.Column(db.Date, nullable=True)
    location = db.Column(db.String(120), default="", nullable=False)
    sale_price = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    purchase = db.relationship("PurchaseOrder", backref=db.backref("items", lazy="dynamic"))
    product = db.relationship("PharmacyProduct")


class FinancialEntry(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_type = db.Column(db.String(20), nullable=False, index=True)
    category = db.Column(db.String(80), default="", nullable=False, index=True)
    description = db.Column(db.String(200), nullable=False)
    counterparty = db.Column(db.String(140), default="", nullable=False)
    amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    status = db.Column(db.String(40), default="open", nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False, index=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    source_ref = db.Column(db.String(120), default="", nullable=False, index=True)
    notes = db.Column(db.Text, default="", nullable=False)


class CashSession(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    opened_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    closed_at = db.Column(db.DateTime, nullable=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    opening_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    closing_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    expected_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    difference_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    notes = db.Column(db.Text, default="", nullable=False)


class StockMovement(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movement_type = db.Column(db.String(30), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("pharmacy_product.id"), nullable=False, index=True)
    lot_id = db.Column(db.Integer, db.ForeignKey("pharmacy_lot.id"), nullable=True, index=True)
    quantity = db.Column(db.Numeric(12, 3), default=0, nullable=False)
    balance_after = db.Column(db.Numeric(12, 3), default=0, nullable=False)
    reference_code = db.Column(db.String(120), default="", nullable=False, index=True)
    notes = db.Column(db.Text, default="", nullable=False)

    product = db.relationship("PharmacyProduct")
    lot = db.relationship("PharmacyLot")


class InventoryCount(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), nullable=False, unique=True, index=True)
    status = db.Column(db.String(30), default="open", nullable=False, index=True)
    count_date = db.Column(db.Date, nullable=False, index=True)
    notes = db.Column(db.Text, default="", nullable=False)


class InventoryCountItem(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inventory_count_id = db.Column(db.Integer, db.ForeignKey("inventory_count.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("pharmacy_product.id"), nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey("pharmacy_lot.id"), nullable=True)
    expected_quantity = db.Column(db.Numeric(12, 3), default=0, nullable=False)
    counted_quantity = db.Column(db.Numeric(12, 3), default=0, nullable=False)
    difference_quantity = db.Column(db.Numeric(12, 3), default=0, nullable=False)
    notes = db.Column(db.Text, default="", nullable=False)

    inventory_count = db.relationship("InventoryCount", backref=db.backref("items", lazy="dynamic"))
    product = db.relationship("PharmacyProduct")
    lot = db.relationship("PharmacyLot")


class WorkflowStage(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    color = db.Column(db.String(20), default="#2d8a4d", nullable=False)
    order_index = db.Column(db.Integer, default=0, nullable=False, index=True)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    is_closed = db.Column(db.Boolean, default=False, nullable=False)


class WorkflowTicket(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), nullable=False, unique=True, index=True)
    title = db.Column(db.String(160), nullable=False)
    customer_name = db.Column(db.String(140), default="", nullable=False)
    customer_phone = db.Column(db.String(40), default="", nullable=False, index=True)
    source_channel = db.Column(db.String(60), default="manual", nullable=False, index=True)
    priority = db.Column(db.String(20), default="normal", nullable=False)
    status = db.Column(db.String(40), default="open", nullable=False, index=True)
    stage_id = db.Column(db.Integer, db.ForeignKey("workflow_stage.id"), nullable=False, index=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("pharmacy_sale.id"), nullable=True, index=True)
    description = db.Column(db.Text, default="", nullable=False)
    assigned_to = db.Column(db.String(120), default="", nullable=False)

    stage = db.relationship("WorkflowStage", backref=db.backref("tickets", lazy="dynamic"))
    sale = db.relationship("PharmacySale")


class InternalChatMessage(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("workflow_ticket.id"), nullable=False, index=True)
    author_name = db.Column(db.String(120), default="Equipe", nullable=False)
    message = db.Column(db.Text, nullable=False)

    ticket = db.relationship("WorkflowTicket", backref=db.backref("messages", lazy="dynamic"))


class IntegrationSetting(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), nullable=False, unique=True, index=True)
    value = db.Column(db.Text, default="", nullable=False)
