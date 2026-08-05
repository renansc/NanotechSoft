from datetime import date
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import inspect, text

from .config import Config
from .extensions import db
from .routes import bp


def create_app():
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    app.register_blueprint(bp)

    with app.app_context():
        db.create_all()
        upgrade_schema()
        seed_defaults()

    return app


def seed_defaults():
    from .models import (
        DistributionTable,
        IntegrationSetting,
        PharmacyCategory,
        PharmacyLot,
        PharmacyProduct,
        PharmacySupplier,
        WorkflowStage,
    )

    if not PharmacyCategory.query.first():
        db.session.add_all(
            [
                PharmacyCategory(name="Medicamentos", description="Linha principal da farmacia."),
                PharmacyCategory(name="Higiene", description="Produtos de higiene e cuidado."),
            ]
        )

    if not PharmacySupplier.query.first():
        db.session.add_all(
            [
                PharmacySupplier(name="Distribuidora Exemplo", document="", phone="", email=""),
            ]
        )

    table_defaults = [
        (1, "Mesa 1", "Esquerda da porta"),
        (2, "Mesa 2", "Direita da porta"),
        (3, "Mesa 3", "Centro"),
        (4, "Mesa 4", "Fundo esquerdo"),
        (5, "Mesa 5", "Fundo direito"),
    ]
    for number, name, location in table_defaults:
        if not DistributionTable.query.filter_by(number=number).first():
            db.session.add(DistributionTable(number=number, name=name, location=location))

    test_category = PharmacyCategory.query.filter_by(name="Produtos de conveniencia").first()
    if not test_category:
        test_category = PharmacyCategory(
            name="Produtos de conveniencia",
            description="Itens de teste para a operacao da distribuidora.",
        )
        db.session.add(test_category)
        db.session.flush()
    test_supplier = PharmacySupplier.query.filter_by(name="Distribuidora Exemplo").first()
    product_defaults = [
        ("TEST-GELO", "Gelo", "22019000", "10.00", "5.00", date(2028, 12, 31)),
        ("TEST-CERVEJA", "Cerveja", "22030000", "8.00", "4.50", date(2027, 12, 31)),
        ("TEST-REFRIGERANTE", "Refrigerante", "22021000", "7.00", "3.50", date(2027, 12, 31)),
        ("TEST-CARVAO", "Carvao vegetal", "44020000", "25.00", "14.00", date(2030, 12, 31)),
    ]
    for sku, name, ncm, sale_price, cost_price, expiration_date in product_defaults:
        product = PharmacyProduct.query.filter_by(sku=sku).first()
        if not product:
            product = PharmacyProduct(
                sku=sku, name=name, unit="UN", sale_price=Decimal(sale_price),
                cost_price=Decimal(cost_price), minimum_stock=Decimal("10"),
                category=test_category, supplier=test_supplier, tracks_inventory=True,
                ncm=ncm, cest="", cfop="5102", fiscal_origin="0", icms_cst="102",
                pis_cst="49", cofins_cst="49", tax_unit="UN", gtin_taxable="SEM GTIN",
            )
            db.session.add(product)
            db.session.flush()
        if not PharmacyLot.query.filter_by(product_id=product.id, lot_code=f"TESTE-{sku}").first():
            db.session.add(PharmacyLot(
                product=product, supplier=test_supplier, lot_code=f"TESTE-{sku}",
                expiration_date=expiration_date, received_at=date.today(),
                quantity_received=Decimal("100"), quantity_available=Decimal("100"),
                purchase_price=Decimal(cost_price), location="Estoque de testes",
            ))

    default_settings = {
        "PHARMACY_CARD_PROVIDER": "",
        "PHARMACY_PIX_PROVIDER": "",
        "PHARMACY_WHATSAPP_NUMBER": "",
        "PHARMACY_WOOCOMMERCE_URL": "",
        "PHARMACY_WOOCOMMERCE_KEY": "",
        "PHARMACY_MERCADO_LIVRE_APP_ID": "",
        "PHARMACY_MERCADO_LIVRE_SELLER_ID": "",
        "COMPANY_NAME": "NanoStore Farmacia",
        "STORE_MODE": "pharmacy",
    }
    for key, value in default_settings.items():
        if not IntegrationSetting.query.filter_by(key=key).first():
            db.session.add(IntegrationSetting(key=key, value=value))

    if not WorkflowStage.query.first():
        db.session.add_all(
            [
                WorkflowStage(name="Novo", color="#2d8a4d", order_index=1, is_default=True),
                WorkflowStage(name="Em atendimento", color="#c48b2a", order_index=2),
                WorkflowStage(name="Separacao", color="#2f6fce", order_index=3),
                WorkflowStage(name="Concluido", color="#4c8f5a", order_index=4, is_closed=True),
            ]
        )

    db.session.commit()


def upgrade_schema():
    inspector = inspect(db.engine)

    if inspector.has_table("pharmacy_category"):
        category_columns = {column["name"] for column in inspector.get_columns("pharmacy_category")}
        if "minimum_profit_margin" not in category_columns:
            db.session.execute(text("ALTER TABLE pharmacy_category ADD COLUMN minimum_profit_margin NUMERIC(8,2) NOT NULL DEFAULT 0"))
        if "suggested_profit_margin" not in category_columns:
            db.session.execute(text("ALTER TABLE pharmacy_category ADD COLUMN suggested_profit_margin NUMERIC(8,2) NOT NULL DEFAULT 0"))

    if inspector.has_table("purchase_order"):
        purchase_columns = {column["name"] for column in inspector.get_columns("purchase_order")}
        if "purchase_type" not in purchase_columns:
            db.session.execute(text("ALTER TABLE purchase_order ADD COLUMN purchase_type VARCHAR(20) NOT NULL DEFAULT 'restock'"))

    if inspector.has_table("purchase_order_item"):
        item_details = {column["name"]: column for column in inspector.get_columns("purchase_order_item")}
        item_columns = set(item_details)
        if "item_type" not in item_columns:
            db.session.execute(text("ALTER TABLE purchase_order_item ADD COLUMN item_type VARCHAR(20) NOT NULL DEFAULT 'restock'"))
        if "free_item_name" not in item_columns:
            db.session.execute(text("ALTER TABLE purchase_order_item ADD COLUMN free_item_name VARCHAR(160) NOT NULL DEFAULT ''"))
        if "sale_price" not in item_columns:
            db.session.execute(text("ALTER TABLE purchase_order_item ADD COLUMN sale_price NUMERIC(12,2) NOT NULL DEFAULT 0"))
        if db.engine.dialect.name == "mysql" and item_details.get("product_id", {}).get("nullable") is False:
            db.session.execute(text("ALTER TABLE purchase_order_item MODIFY COLUMN product_id INTEGER NULL"))

    if inspector.has_table("pharmacy_payment"):
        payment_columns = {column["name"] for column in inspector.get_columns("pharmacy_payment")}
        if "cash_session_id" not in payment_columns:
            db.session.execute(text("ALTER TABLE pharmacy_payment ADD COLUMN cash_session_id INTEGER NULL"))
            db.session.execute(text("CREATE INDEX ix_pharmacy_payment_cash_session_id ON pharmacy_payment (cash_session_id)"))

    if inspector.has_table("pharmacy_product"):
        product_columns = {column["name"] for column in inspector.get_columns("pharmacy_product")}
        fiscal_columns = {
            "tracks_inventory": "BOOLEAN NOT NULL DEFAULT 1",
            "ncm": "VARCHAR(8) NOT NULL DEFAULT ''", "cest": "VARCHAR(7) NOT NULL DEFAULT ''",
            "cfop": "VARCHAR(4) NOT NULL DEFAULT '5102'", "fiscal_origin": "VARCHAR(1) NOT NULL DEFAULT '0'",
            "icms_cst": "VARCHAR(3) NOT NULL DEFAULT ''", "pis_cst": "VARCHAR(2) NOT NULL DEFAULT ''",
            "cofins_cst": "VARCHAR(2) NOT NULL DEFAULT ''", "tax_unit": "VARCHAR(6) NOT NULL DEFAULT 'UN'",
            "gtin_taxable": "VARCHAR(14) NOT NULL DEFAULT 'SEM GTIN'", "benefit_code": "VARCHAR(10) NOT NULL DEFAULT ''",
            "has_tax_benefit": "BOOLEAN NOT NULL DEFAULT 0", "anvisa_code": "VARCHAR(13) NOT NULL DEFAULT ''",
            "max_consumer_price": "NUMERIC(12,2) NOT NULL DEFAULT 0", "ibs_cbs_cst": "VARCHAR(3) NOT NULL DEFAULT ''",
            "tax_classification": "VARCHAR(6) NOT NULL DEFAULT ''", "ibs_uf_rate": "NUMERIC(7,4) NOT NULL DEFAULT 0",
            "ibs_mun_rate": "NUMERIC(7,4) NOT NULL DEFAULT 0", "cbs_rate": "NUMERIC(7,4) NOT NULL DEFAULT 0",
        }
        for column, definition in fiscal_columns.items():
            if column not in product_columns:
                db.session.execute(text(f"ALTER TABLE pharmacy_product ADD COLUMN {column} {definition}"))

    if inspector.has_table("pharmacy_sale_item") and db.engine.dialect.name == "mysql":
        sale_item_details = {column["name"]: column for column in inspector.get_columns("pharmacy_sale_item")}
        if sale_item_details.get("lot_id", {}).get("nullable") is False:
            db.session.execute(text("ALTER TABLE pharmacy_sale_item MODIFY COLUMN lot_id INTEGER NULL"))

    if inspector.has_table("pharmacy_sale"):
        sale_columns = {column["name"] for column in inspector.get_columns("pharmacy_sale")}
        delivery_columns = {
            "customer_id": "INTEGER NULL", "fulfillment_type": "VARCHAR(20) NOT NULL DEFAULT 'counter'",
            "table_reference": "VARCHAR(40) NOT NULL DEFAULT ''", "delivery_address": "VARCHAR(300) NOT NULL DEFAULT ''",
            "delivery_status": "VARCHAR(30) NOT NULL DEFAULT 'new'", "completed_at": "DATETIME NULL",
        }
        for column, definition in delivery_columns.items():
            if column not in sale_columns:
                db.session.execute(text(f"ALTER TABLE pharmacy_sale ADD COLUMN {column} {definition}"))
        sale_indexes = {index["name"] for index in inspector.get_indexes("pharmacy_sale")}
        if "ix_pharmacy_sale_completed_at" not in sale_indexes:
            db.session.execute(text("CREATE INDEX ix_pharmacy_sale_completed_at ON pharmacy_sale (completed_at)"))

    db.session.commit()
