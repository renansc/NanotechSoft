import unittest
from unittest.mock import patch
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from flask import Flask
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nanostore.extensions import db
from nanostore.models import CashMovement, CashSession, DistributionTable, FinancialEntry, IntegrationSetting, PharmacyCategory, PharmacyCustomer, PharmacyLot, PharmacyPayment, PharmacyProduct, PharmacySale, PharmacySupplier, StockMovement
from nanostore.routes import bp, _format_local_datetime


class CashFlowTest(unittest.TestCase):
    def setUp(self):
        source_dir = Path(__file__).resolve().parents[1] / "nanostore"
        self.app = Flask(__name__, template_folder=str(source_dir / "templates"), static_folder=str(source_dir / "static"))
        self.app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", TESTING=True)
        db.init_app(self.app)
        self.app.register_blueprint(bp)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def make_sale(self, code="S-1", total="9.00"):
        sale = PharmacySale(code=code, customer_name="Cliente", total_amount=Decimal(total))
        db.session.add(sale)
        db.session.flush()
        db.session.add(FinancialEntry(
            entry_type="receivable", description="Venda", amount=Decimal(total),
            status="open", due_date=date.today(), source_ref=code,
        ))
        db.session.commit()
        return sale

    def test_payment_requires_open_cash(self):
        sale = self.make_sale()
        response = self.app.test_client().post("/api/payments/process", json={"sale_id": sale.id, "method": "cash", "amount": "9"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PharmacyPayment.query.count(), 0)

    def test_payment_updates_only_current_cash_session_and_receivable(self):
        old = CashSession(status="closed", opening_amount=Decimal("20"), expected_amount=Decimal("20"))
        current = CashSession(status="open", opening_amount=Decimal("50"), expected_amount=Decimal("50"))
        db.session.add_all([old, current])
        sale = self.make_sale()

        response = self.app.test_client().post("/api/payments/process", json={"sale_id": sale.id, "method": "cash", "amount": "9"})
        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.refresh(current)
        db.session.refresh(old)
        db.session.refresh(sale)
        payment = PharmacyPayment.query.one()
        receivable = FinancialEntry.query.filter_by(source_ref=sale.code).one()
        self.assertEqual(payment.cash_session_id, current.id)
        self.assertEqual(Decimal(current.expected_amount), Decimal("59"))
        self.assertEqual(Decimal(old.expected_amount), Decimal("20"))
        self.assertEqual(sale.status, "paid")
        self.assertEqual(receivable.status, "paid")

    def test_rejects_payment_above_balance(self):
        db.session.add(CashSession(status="open", opening_amount=0, expected_amount=0))
        sale = self.make_sale(total="9")
        response = self.app.test_client().post("/api/payments/process", json={"sale_id": sale.id, "method": "pix", "amount": "10"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PharmacyPayment.query.count(), 0)

    def test_new_paid_sale_credits_open_cash_in_same_transaction(self):
        cash = CashSession(status="open", opening_amount=Decimal("50"), expected_amount=Decimal("50"))
        item = PharmacyProduct(sku="P-1", name="Produto", sale_price=Decimal("9"))
        db.session.add_all([cash, item])
        db.session.flush()
        lot = PharmacyLot(
            product_id=item.id, lot_code="L-1", expiration_date=date(2027, 1, 1), received_at=date.today(),
            quantity_received=Decimal("2"), quantity_available=Decimal("2"), purchase_price=Decimal("4"),
        )
        db.session.add(lot)
        db.session.commit()

        response = self.app.test_client().post("/api/sales", json={
            "customer_name": "Cliente", "payment_method": "cash",
            "items": [{"product_id": item.id, "quantity": "1", "unit_price": "9", "discount_amount": "0"}],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        sale = PharmacySale.query.one()
        payment = PharmacyPayment.query.one()
        receivable = FinancialEntry.query.filter_by(source_ref=sale.code).one()
        db.session.refresh(cash)
        db.session.refresh(lot)
        self.assertEqual(sale.status, "paid")
        self.assertEqual(payment.cash_session_id, cash.id)
        self.assertEqual(receivable.status, "paid")
        self.assertEqual(Decimal(cash.expected_amount), Decimal("59"))
        self.assertEqual(Decimal(lot.quantity_available), Decimal("1"))
        movement = StockMovement.query.filter_by(product_id=item.id, movement_type="sale").one()
        self.assertEqual(Decimal(movement.quantity), Decimal("-1"))

    def test_service_sale_does_not_require_stock_or_lot(self):
        service = PharmacyProduct(
            sku="SERV-1", name="Instalacao", sale_price=Decimal("120"), tracks_inventory=False,
        )
        db.session.add(service)
        db.session.commit()
        response = self.app.test_client().post("/api/sales", json={
            "customer_name": "Cliente", "payment_method": "pending",
            "items": [{"product_id": service.id, "quantity": "1", "unit_price": "120"}],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        sale = PharmacySale.query.one()
        sale_item = sale.items.one()
        self.assertIsNone(sale_item.lot_id)
        self.assertEqual(Decimal(sale.total_amount), Decimal("120"))

    def test_reports_show_cash_orders_stock_and_customers(self):
        cash = CashSession(status="open", opening_amount=Decimal("100"), expected_amount=Decimal("115"))
        customer = PharmacyCustomer(
            name="Cliente Relatorio", phone="44999999999", address="Rua Teste",
            address_number="10", neighborhood="Centro", city="Astorga", state="PR",
        )
        product = PharmacyProduct(
            sku="REL-1", name="Produto Relatorio", barcode="789000000001",
            sale_price=Decimal("10"), cost_price=Decimal("4"), minimum_stock=Decimal("2"),
        )
        db.session.add_all([cash, customer, product])
        db.session.flush()
        lot = PharmacyLot(
            product_id=product.id, lot_code="LOTE-REL", expiration_date=date(2027, 1, 1),
            received_at=date.today(), quantity_received=Decimal("10"),
            quantity_available=Decimal("8"), purchase_price=Decimal("4"), location="A1",
        )
        sale = PharmacySale(
            code="PED-REL", customer_name=customer.name, customer_id=customer.id,
            total_amount=Decimal("30"), status="paid", delivery_status="ready",
        )
        db.session.add_all([lot, sale])
        db.session.flush()
        db.session.add_all([
            CashMovement(
                cash_session_id=cash.id, direction="in", category="Reforco",
                description="Entrada teste", amount=Decimal("5"),
            ),
            CashMovement(
                cash_session_id=cash.id, direction="out", category="Despesa",
                description="Saida teste", amount=Decimal("20"),
            ),
            PharmacyPayment(
                sale_id=sale.id, cash_session_id=cash.id, method="cash",
                amount=Decimal("30"), status="paid", transaction_reference="REL-PAG",
            ),
        ])
        db.session.commit()

        response = self.app.test_client().get("/")
        page = response.get_data(as_text=True)

        self.assertEqual(200, response.status_code)
        for report_name in (
            "Movimento de caixa", "Status de pedidos", "Posicao de estoque",
            "Itens de estoque", "Entradas e saidas", "Cadastro de clientes",
        ):
            self.assertIn(report_name, page)
        self.assertIn("PED-REL", page)
        self.assertIn("LOTE-REL", page)
        self.assertIn("Cliente Relatorio", page)
        self.assertIn("R$ 135.00", page)
        self.assertIn("R$ 20.00", page)
        self.assertIn("R$ 115.00", page)
        self.assertIn('id="report-export-csv"', page)
        self.assertIn('id="report-print"', page)
        self.assertIn('id="estoque" data-view', page)
        self.assertIn("Visao atual do estoque", page)
        self.assertIn("R$ 32.00", page)
        self.assertIn('id="documentacao" data-view', page)
        self.assertIn("Manual de operacao", page)
        self.assertIn("Editar, cancelar ou excluir uma venda", page)
        self.assertIn("Correcao de lancamentos", page)

    def test_template_has_only_the_real_body_closing_tag(self):
        template_path = Path(__file__).resolve().parents[1] / "nanostore" / "templates" / "index.html"
        template = template_path.read_text(encoding="utf-8")

        self.assertEqual(1, template.count("</body>"))

    def test_registered_products_can_be_listed_and_fully_edited(self):
        category = PharmacyCategory(name="Bebidas")
        supplier = PharmacySupplier(name="Fornecedor teste")
        product = PharmacyProduct(sku="ITEM-1", name="Nome antigo", barcode="789000000001")
        other = PharmacyProduct(sku="ITEM-2", name="Outro item", barcode="789000000002")
        db.session.add_all([category, supplier, product, other])
        db.session.commit()
        client = self.app.test_client()

        page = client.get("/").get_data(as_text=True)
        self.assertIn("Medicamentos e produtos cadastrados", page)
        self.assertIn("Nome antigo", page)
        self.assertIn('class="secondary-btn product-edit-btn"', page)
        self.assertIn("Consultar NCM na Receita", page)
        self.assertIn("validacao estrutural", page.lower())
        self.assertIn("Assistir tributacao", page)
        self.assertIn("Configurar emitente", page)
        self.assertIn('id="sidebar-toggle"', page)
        self.assertIn('class="subnav config-subnav"', page)
        self.assertIn('id="config-emitente" data-subview', page)
        self.assertIn('id="config-integracoes" data-subview hidden', page)
        self.assertIn('class="field-block config-field-wide"><span>Razao social', page)
        self.assertEqual(2, page.count('class="settings-form config-form-grid"'))

        response = client.patch(f"/api/products/{product.id}", json={
            "sku": "ITEM-EDITADO", "name": "Nome novo", "barcode": "789000000003",
            "brand": "Marca", "active_ingredient": "Composto", "unit": "CX",
            "cost_price": "4.50", "sale_price": "8.90", "minimum_stock": "3",
            "category_id": category.id, "supplier_id": supplier.id,
            "tracks_inventory": False, "is_active": True,
            "ncm": "22021000", "cfop": "5102", "fiscal_origin": "0",
        })
        self.assertEqual(200, response.status_code, response.get_json())
        db.session.refresh(product)
        self.assertEqual("ITEM-EDITADO", product.sku)
        self.assertEqual("Nome novo", product.name)
        self.assertEqual(category.id, product.category_id)
        self.assertEqual(supplier.id, product.supplier_id)
        self.assertFalse(product.tracks_inventory)
        self.assertEqual(Decimal("8.90"), Decimal(product.sale_price))

        duplicate = client.patch(f"/api/products/{product.id}", json={"sku": other.sku})
        self.assertEqual(400, duplicate.status_code)
        self.assertIn("SKU ja cadastrado", duplicate.get_json()["error"])

    def test_fiscal_assistance_requires_crt_and_returns_compatible_codes(self):
        client = self.app.test_client()
        payload = {
            "sku": "CARVAO", "name": "Carvao vegetal", "ncm": "44020000",
            "icms_cst": "102", "pis_cst": "49", "cofins_cst": "49",
        }
        missing = client.post("/api/fiscal/product-assistance", json=payload)
        self.assertEqual(200, missing.status_code, missing.get_json())
        self.assertFalse(missing.get_json()["regime_configured"])
        self.assertIn("configure o CRT", " ".join(missing.get_json()["fiscal_errors"]))

        db.session.add(IntegrationSetting(key="FISCAL_CRT", value="1"))
        db.session.commit()
        assisted = client.post("/api/fiscal/product-assistance", json=payload)
        data = assisted.get_json()
        self.assertTrue(data["regime_configured"])
        self.assertEqual("CSOSN", data["field_label"])
        self.assertIn("102", [option["code"] for option in data["options"]])
        self.assertEqual("5102", data["suggestions"]["cfop"])

    def test_every_store_mode_renders_its_interface(self):
        expected = {
            "pharmacy": "Operacao da farmacia", "store": "Painel da loja",
            "distributor": "Dashboard operacional", "commerce": "Gestao comercial",
            "food": "Operacao de alimentos", "services": "Central de servicos",
        }
        setting = IntegrationSetting(key="STORE_MODE", value="pharmacy")
        db.session.add(setting)
        db.session.commit()
        client = self.app.test_client()
        for key, headline in expected.items():
            setting.value = key
            db.session.commit()
            response = client.get("/")
            self.assertEqual(response.status_code, 200, f"{key}: {response.get_data(as_text=True)}")
            html = response.get_data(as_text=True)
            self.assertIn(headline, html, key)
            if key == "distributor":
                self.assertIn('data-mode-accent="gold"', html)
                for marker in (
                    "Dashboard operacional", 'data-dashboard-report="cash"', 'data-dashboard-report="orders"',
                    'data-dashboard-report="stock"', "Entrada ou saida", "Kanban de pedidos",
                    "Notas dos pedidos", "Novo cliente do pedido", "Codigo / bipe", "Ler pela webcam",
                    "Venda direta no caixa", 'id="cash-sale-barcode-input"', 'id="cash-sale-items-json"',
                    "Bipar com camera", "Leitura na venda direta", "BARCODE_INPUT_MODE",
                    "vendor/zxing-browser.min.js", 'data-barcode-input-mode="auto"',
                    "Buscar item similar", 'id="similar-product-modal"', "/api/products/similar",
                    "decodeFromVideoElement", "scannerVideo.srcObject = scannerStream",
                    'data-function-nav="estoque-visao"', 'data-function-nav="cadastros-produtos"',
                    'data-function-nav="lancamentos-caixa"', 'data-function-nav="documentacao"',
                    "activateFunctionPanel", 'data-open-function="produto-novo"',
                    "data-order-edit", "data-order-delete", 'data-target="estoque"',
                    'data-target="relatorios"', 'data-target="documentacao"',
                    'class="menu-link" data-target="configuracao">Configuracao',
                ):
                    self.assertIn(marker, html)

    def test_saved_barcode_input_mode_is_rendered(self):
        client = self.app.test_client()
        saved = client.post("/api/settings", json={"settings": {"BARCODE_INPUT_MODE": "camera"}})
        self.assertEqual(200, saved.status_code, saved.get_json())
        html = client.get("/").get_data(as_text=True)
        self.assertIn('data-barcode-input-mode="camera"', html)
        self.assertIn('<option value="camera" selected>', html)
        rejected = client.post("/api/settings", json={"settings": {"BARCODE_INPUT_MODE": "invalido"}})
        self.assertEqual(400, rejected.status_code)
        self.assertEqual("camera", IntegrationSetting.query.filter_by(key="BARCODE_INPUT_MODE").one().value)

    def test_company_logo_can_be_uploaded_served_and_removed(self):
        image_data = BytesIO()
        Image.new("RGBA", (120, 80), (218, 165, 32, 255)).save(image_data, format="PNG")
        client = self.app.test_client()
        with TemporaryDirectory() as assets_dir, patch.dict(
            "os.environ", {"NANOSTORE_COMPANY_ASSET_DIR": assets_dir}
        ):
            uploaded = client.post(
                "/api/company/logo",
                data={"logo": (BytesIO(image_data.getvalue()), "marca.png")},
                content_type="multipart/form-data",
            )
            self.assertEqual(200, uploaded.status_code, uploaded.get_json())
            self.assertEqual("logo.png", IntegrationSetting.query.filter_by(key="COMPANY_LOGO_FILE").one().value)
            served = client.get("/api/company/logo")
            self.assertEqual(200, served.status_code)
            self.assertEqual("image/png", served.mimetype)
            served.close()
            page = client.get("/").get_data(as_text=True)
            self.assertIn('class="brand-logo"', page)
            removed = client.delete("/api/company/logo")
            self.assertEqual(200, removed.status_code, removed.get_json())
            self.assertEqual(404, client.get("/api/company/logo").status_code)

    def test_company_logo_rejects_non_image_file(self):
        client = self.app.test_client()
        with TemporaryDirectory() as assets_dir, patch.dict(
            "os.environ", {"NANOSTORE_COMPANY_ASSET_DIR": assets_dir}
        ):
            response = client.post(
                "/api/company/logo",
                data={"logo": (BytesIO(b"nao e imagem"), "marca.png")},
                content_type="multipart/form-data",
            )
        self.assertEqual(400, response.status_code)

    def test_order_purchase_time_is_formatted_in_local_timezone(self):
        purchase_time = datetime(2026, 8, 5, 18, 32)
        self.assertEqual("05/08/2026 15:32", _format_local_datetime(purchase_time))

    def test_distributor_dashboard_summarizes_cash_orders_and_stock(self):
        setting = IntegrationSetting(key="STORE_MODE", value="distributor")
        cash = CashSession(status="open", opening_amount=Decimal("50"), expected_amount=Decimal("50"))
        item = PharmacyProduct(
            sku="DASH-1", name="Produto Dashboard", sale_price=Decimal("12"),
            minimum_stock=Decimal("2"),
        )
        db.session.add_all([setting, cash, item])
        db.session.flush()
        db.session.add_all([
            PharmacyLot(
                product_id=item.id, lot_code="DASH-L1", expiration_date=date(2028, 1, 1), received_at=date.today(),
                quantity_received=Decimal("5"), quantity_available=Decimal("5"), purchase_price=Decimal("6"),
            ),
            CashMovement(
                cash_session_id=cash.id, direction="in", category="Teste",
                description="Reforco dashboard", amount=Decimal("25"),
            ),
            PharmacySale(code="DASH-PEDIDO", customer_name="Cliente Dashboard", total_amount=Decimal("12"), delivery_status="ready"),
        ])
        db.session.commit()
        response = self.app.test_client().get("/")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        html = response.get_data(as_text=True)
        for marker in ("Produto Dashboard", "Reforco dashboard", "DASH-PEDIDO", "Separado"):
            self.assertIn(marker, html)

    def test_cash_entries_and_withdrawals_change_expected_balance(self):
        cash = CashSession(status="open", opening_amount=Decimal("100"), expected_amount=Decimal("100"))
        db.session.add(cash)
        db.session.commit()
        client = self.app.test_client()
        self.assertEqual(client.post("/api/cash/movements", json={"direction": "in", "description": "Reforco", "amount": "25"}).status_code, 200)
        self.assertEqual(client.post("/api/cash/movements", json={"direction": "out", "description": "Frete", "amount": "10"}).status_code, 200)
        db.session.refresh(cash)
        self.assertEqual(Decimal(cash.expected_amount), Decimal("115"))
        self.assertEqual(CashMovement.query.count(), 2)

    def test_delivery_order_requires_registered_customer_and_tracks_fulfillment(self):
        item = PharmacyProduct(sku="D-1", name="Caixa", sale_price=Decimal("20"))
        customer = PharmacyCustomer(name="Mercado", phone="41999999999", address="Rua Central", address_number="10")
        db.session.add_all([item, customer])
        db.session.flush()
        db.session.add(PharmacyLot(
            product_id=item.id, lot_code="DL-1", expiration_date=date(2027, 1, 1), received_at=date.today(),
            quantity_received=Decimal("5"), quantity_available=Decimal("5"), purchase_price=Decimal("10"),
        ))
        db.session.commit()
        client = self.app.test_client()
        missing_customer = client.post("/api/sales", json={
            "customer_name": "Avulso", "fulfillment_type": "delivery",
            "items": [{"product_id": item.id, "quantity": "1", "unit_price": "20"}],
        })
        self.assertEqual(missing_customer.status_code, 400)
        response = client.post("/api/sales", json={
            "customer_id": customer.id, "fulfillment_type": "delivery", "payment_method": "pending",
            "items": [{"product_id": item.id, "quantity": "1", "unit_price": "20"}],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        sale = PharmacySale.query.one()
        self.assertEqual(sale.customer_id, customer.id)
        self.assertIn("Rua Central", sale.delivery_address)
        status = client.patch(f"/api/sales/{sale.id}/fulfillment", json={"delivery_status": "picking"})
        self.assertEqual(status.status_code, 200)
        db.session.refresh(sale)
        self.assertEqual(sale.delivery_status, "picking")

    def test_order_can_create_and_select_customer_during_sale_flow(self):
        client = self.app.test_client()
        response = client.post("/api/customers", json={
            "name": "Cliente Rapido", "phone": "(41) 99999-1234",
            "address": "Rua do Pedido", "address_number": "25", "city": "Curitiba", "state": "PR",
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        customer = response.get_json()["customer"]
        self.assertEqual(customer["phone"], "41999991234")
        self.assertIn("Rua do Pedido", customer["full_address"])

    def test_order_kanban_accepts_operational_statuses(self):
        sale = self.make_sale()
        client = self.app.test_client()
        for status in ("new", "ready", "out_for_delivery", "delivered"):
            response = client.patch(f"/api/sales/{sale.id}/fulfillment", json={"delivery_status": status})
            self.assertEqual(response.status_code, 200, response.get_json())
            db.session.refresh(sale)
            self.assertEqual(sale.delivery_status, status)

    def test_finalized_order_stays_today_and_leaves_kanban_next_day(self):
        db.session.add(IntegrationSetting(key="STORE_MODE", value="distributor"))
        today_sale = PharmacySale(
            code="FINAL-HOJE", customer_name="Cliente hoje", total_amount=Decimal("10"),
            delivery_status="completed", completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        old_sale = PharmacySale(
            code="FINAL-ONTEM", customer_name="Cliente ontem", total_amount=Decimal("10"),
            delivery_status="completed", completed_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        )
        pending_sale = PharmacySale(
            code="PENDENTE-HOJE", customer_name="Cliente pendente", total_amount=Decimal("10"),
            delivery_status="ready", created_at=datetime(2026, 8, 5, 18, 32),
        )
        db.session.add_all([today_sale, old_sale, pending_sale])
        db.session.commit()
        client = self.app.test_client()

        page = client.get("/").get_data(as_text=True)
        self.assertIn(f'data-sale-id="{today_sale.id}" data-order-status="completed"', page)
        self.assertNotIn(f'data-sale-id="{old_sale.id}" data-order-status="completed"', page)
        self.assertIn(f'data-sale-id="{pending_sale.id}" data-order-status="ready"', page)
        self.assertIn('class="order-created-at"', page)
        self.assertIn("05/08/2026 15:32", page)
        self.assertIn("Finalizados hoje", page)
        self.assertIn("data-order-finalize", page)

        reopened = client.patch(
            f"/api/sales/{today_sale.id}/fulfillment", json={"delivery_status": "new"},
        )
        self.assertEqual(200, reopened.status_code, reopened.get_json())
        db.session.refresh(today_sale)
        self.assertEqual("new", today_sale.delivery_status)
        self.assertIsNone(today_sale.completed_at)

        finalized = client.patch(
            f"/api/sales/{today_sale.id}/fulfillment", json={"delivery_status": "completed"},
        )
        self.assertEqual(200, finalized.status_code, finalized.get_json())
        db.session.refresh(today_sale)
        self.assertEqual("completed", today_sale.delivery_status)
        self.assertIsNotNone(today_sale.completed_at)

    def test_table_order_requires_table_reference(self):
        response = self.app.test_client().post("/api/sales", json={
            "customer_name": "Mesa", "fulfillment_type": "table",
            "items": [{"product_id": 999, "quantity": "1", "unit_price": "1"}],
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("mesa", response.get_json()["error"].lower())

    def test_table_order_uses_registered_table_snapshot(self):
        table = DistributionTable(number=1, name="Mesa 1", location="Esquerda da porta")
        item = PharmacyProduct(sku="M-1", name="Gelo", sale_price=Decimal("10"))
        db.session.add_all([table, item])
        db.session.flush()
        db.session.add(PharmacyLot(
            product_id=item.id, lot_code="MESA-L1", expiration_date=date(2028, 1, 1), received_at=date.today(),
            quantity_received=Decimal("5"), quantity_available=Decimal("5"), purchase_price=Decimal("5"),
        ))
        db.session.commit()
        response = self.app.test_client().post("/api/sales", json={
            "customer_name": "Mesa", "fulfillment_type": "table", "table_id": table.id,
            "items": [{"product_id": item.id, "quantity": "1", "unit_price": "10"}],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(PharmacySale.query.one().table_reference, "1 - Mesa 1 - Esquerda da porta")

    def test_order_pdf_supports_a4_and_thermal_formats(self):
        sale = self.make_sale()
        client = self.app.test_client()
        for format_name in ("a4", "thermal58", "thermal80"):
            response = client.get(f"/api/orders/{sale.id}/pdf?format={format_name}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "application/pdf")
            self.assertTrue(response.data.startswith(b"%PDF"))

    def test_product_barcode_can_be_registered_looked_up_and_not_duplicated(self):
        client = self.app.test_client()
        created = client.post("/api/products", json={
            "sku": "BIP-1", "name": "Produto com bipe", "barcode": "7891234567890",
            "sale_price": "15", "cost_price": "8", "tracks_inventory": True,
        })
        self.assertEqual(created.status_code, 200, created.get_json())
        lookup = client.get("/api/products/lookup?code=7891234567890")
        self.assertEqual(lookup.status_code, 200, lookup.get_json())
        self.assertEqual(lookup.get_json()["product"]["sku"], "BIP-1")
        duplicate = client.post("/api/products", json={
            "sku": "BIP-2", "name": "Codigo repetido", "barcode": "7891234567890",
        })
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("ja cadastrado", duplicate.get_json()["error"])

    def test_similar_product_search_ranks_catalog_and_can_exclude_current_item(self):
        category = PharmacyCategory(name="Bebidas")
        db.session.add(category)
        db.session.flush()
        beer = PharmacyProduct(
            sku="SIM-CERV-1", name="Cerveja Pilsen Lata 350ml", barcode="7891111111111",
            category_id=category.id, ncm="22030000", icms_cst="102", pis_cst="04", cofins_cst="04",
        )
        soda = PharmacyProduct(
            sku="SIM-REFRI-1", name="Refrigerante Cola 350ml", barcode="7892222222222",
            category_id=category.id, ncm="22021000",
        )
        db.session.add_all([beer, soda])
        db.session.commit()
        client = self.app.test_client()

        response = client.get("/api/products/similar?name=cerveja+pilsen&ncm=22030000")
        self.assertEqual(200, response.status_code, response.get_json())
        items = response.get_json()["items"]
        self.assertEqual(beer.id, items[0]["product"]["id"])
        self.assertIn("mesmo NCM", items[0]["reasons"])
        self.assertEqual("04", items[0]["product"]["pis_cst"])

        excluded = client.get(f"/api/products/similar?name=cerveja&exclude_id={beer.id}")
        self.assertNotIn(beer.id, [item["product"]["id"] for item in excluded.get_json()["items"]])
        self.assertEqual(400, client.get("/api/products/similar").status_code)

    @patch("nanostore.routes._search_open_food_facts")
    @patch("nanostore.routes._search_official_ncm")
    def test_similar_product_search_combines_external_catalog_and_official_ncm(self, search_ncm, search_catalog):
        search_ncm.return_value = [{
            "score": 90, "reasons": ["descricao da tabela NCM oficial"],
            "source": "receita_ncm", "source_label": "Receita Federal - NCM oficial",
            "product": {"name": "Cervejas de malte", "ncm": "22030000", "unit": "UN", "tax_unit": "UN"},
        }]
        search_catalog.return_value = [{
            "score": 110, "reasons": ["produto encontrado por codigo"],
            "source": "open_food_facts", "source_label": "Open Food Facts",
            "external_quantity": "350 ml",
            "product": {"sku": "GTIN-7891234567890", "name": "Cerveja Pilsen", "barcode": "7891234567890", "brand": "Marca Teste"},
        }]
        response = self.app.test_client().get(
            "/api/products/similar?name=cerveja&barcode=7891234567890&external=1"
        )
        self.assertEqual(200, response.status_code, response.get_json())
        data = response.get_json()
        sources = {item["source"] for item in data["items"]}
        self.assertIn("receita_ncm", sources)
        self.assertIn("open_food_facts", sources)
        catalog = next(item for item in data["items"] if item["source"] == "open_food_facts")
        self.assertNotIn("ncm", catalog["product"])
        self.assertEqual("Open Food Facts", catalog["source_label"])

    def make_stocked_order(self, payment_method="pending", quantity="1", price="10"):
        product = PharmacyProduct(sku="EDIT-1", name="Produto editavel", sale_price=Decimal(price))
        db.session.add(product)
        db.session.flush()
        lot = PharmacyLot(
            product_id=product.id, lot_code="EDIT-L1", expiration_date=date(2028, 1, 1), received_at=date.today(),
            quantity_received=Decimal("5"), quantity_available=Decimal("5"), purchase_price=Decimal("4"),
        )
        db.session.add(lot)
        db.session.commit()
        response = self.app.test_client().post("/api/sales", json={
            "customer_name": "Cliente original", "payment_method": payment_method,
            "items": [{"product_id": product.id, "quantity": quantity, "unit_price": price}],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        return PharmacySale.query.one(), product, lot

    def test_order_edit_replaces_items_stock_and_receivable(self):
        sale, product, lot = self.make_stocked_order()
        response = self.app.test_client().patch(f"/api/sales/{sale.id}", json={
            "customer_name": "Cliente alterado", "fulfillment_type": "counter",
            "items": [{"product_id": product.id, "quantity": "2", "unit_price": "10"}],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.refresh(sale)
        db.session.refresh(lot)
        receivable = FinancialEntry.query.filter_by(source_ref=sale.code).one()
        self.assertEqual(sale.customer_name, "Cliente alterado")
        self.assertEqual(Decimal(sale.total_amount), Decimal("20"))
        self.assertEqual(Decimal(lot.quantity_available), Decimal("3"))
        self.assertEqual(Decimal(receivable.amount), Decimal("20"))
        self.assertEqual(sale.items.count(), 1)

    def test_paid_order_edit_preserves_cash_and_rejects_total_below_paid(self):
        cash = CashSession(status="open", opening_amount=Decimal("50"), expected_amount=Decimal("50"))
        db.session.add(cash)
        db.session.commit()
        sale, product, lot = self.make_stocked_order(payment_method="cash")
        increased = self.app.test_client().patch(f"/api/sales/{sale.id}", json={
            "customer_name": "Cliente original", "fulfillment_type": "counter",
            "items": [{"product_id": product.id, "quantity": "2", "unit_price": "10"}],
        })
        self.assertEqual(increased.status_code, 200, increased.get_json())
        db.session.refresh(cash)
        db.session.refresh(sale)
        self.assertEqual(Decimal(cash.expected_amount), Decimal("60"))
        self.assertEqual(sale.status, "partially_paid")

        rejected = self.app.test_client().patch(f"/api/sales/{sale.id}", json={
            "customer_name": "Cliente original", "fulfillment_type": "counter",
            "items": [{"product_id": product.id, "quantity": "1", "unit_price": "5"}],
        })
        self.assertEqual(rejected.status_code, 400, rejected.get_json())
        db.session.refresh(sale)
        db.session.refresh(lot)
        self.assertEqual(Decimal(sale.total_amount), Decimal("20"))
        self.assertEqual(Decimal(lot.quantity_available), Decimal("3"))

    def test_delete_paid_order_reverses_current_cash_and_restores_stock(self):
        cash = CashSession(status="open", opening_amount=Decimal("50"), expected_amount=Decimal("50"))
        db.session.add(cash)
        db.session.commit()
        sale, _, lot = self.make_stocked_order(payment_method="cash")
        response = self.app.test_client().delete(f"/api/sales/{sale.id}")
        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.refresh(cash)
        db.session.refresh(sale)
        db.session.refresh(lot)
        self.assertEqual(Decimal(cash.expected_amount), Decimal("50"))
        self.assertEqual(Decimal(lot.quantity_available), Decimal("5"))
        self.assertEqual(sale.status, "cancelled")
        self.assertEqual(PharmacyPayment.query.one().status, "reversed")
        self.assertEqual(FinancialEntry.query.filter_by(source_ref=sale.code).one().status, "cancelled")
        self.assertEqual(StockMovement.query.filter_by(movement_type="sale_cancel").count(), 1)
        payment_attempt = self.app.test_client().post(
            "/api/payments/process", json={"sale_id": sale.id, "method": "cash", "amount": "10"},
        )
        status_attempt = self.app.test_client().patch(
            f"/api/sales/{sale.id}/fulfillment", json={"delivery_status": "new"},
        )
        self.assertEqual(payment_attempt.status_code, 400)
        self.assertEqual(status_attempt.status_code, 400)

    def test_delete_order_from_closed_cash_records_refund_in_current_cash(self):
        old_cash = CashSession(status="open", opening_amount=Decimal("50"), expected_amount=Decimal("50"))
        db.session.add(old_cash)
        db.session.commit()
        sale, _, _ = self.make_stocked_order(payment_method="cash")
        old_cash.status = "closed"
        old_cash.closing_amount = old_cash.expected_amount
        current_cash = CashSession(status="open", opening_amount=Decimal("100"), expected_amount=Decimal("100"))
        db.session.add(current_cash)
        db.session.commit()

        response = self.app.test_client().delete(f"/api/sales/{sale.id}")
        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.refresh(old_cash)
        db.session.refresh(current_cash)
        refund = CashMovement.query.filter_by(cash_session_id=current_cash.id, category="Estorno de venda").one()
        self.assertEqual(Decimal(old_cash.expected_amount), Decimal("60"))
        self.assertEqual(Decimal(current_cash.expected_amount), Decimal("90"))
        self.assertEqual(Decimal(refund.amount), Decimal("10"))


if __name__ == "__main__":
    unittest.main()
