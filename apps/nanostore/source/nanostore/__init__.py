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
    from .models import IntegrationSetting, PharmacyCategory, PharmacySupplier, WorkflowStage

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

    default_settings = {
        "PHARMACY_CARD_PROVIDER": "",
        "PHARMACY_PIX_PROVIDER": "",
        "PHARMACY_WHATSAPP_NUMBER": "",
        "PHARMACY_WOOCOMMERCE_URL": "",
        "PHARMACY_WOOCOMMERCE_KEY": "",
        "PHARMACY_MERCADO_LIVRE_APP_ID": "",
        "PHARMACY_MERCADO_LIVRE_SELLER_ID": "",
        "COMPANY_NAME": "NanoStore Farmacia",
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

    db.session.commit()
