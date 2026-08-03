import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nanostore.extensions import db
from nanostore.models import CashMovement, CashSession, DistributionTable, FinancialEntry, IntegrationSetting, PharmacyCustomer, PharmacyLot, PharmacyPayment, PharmacyProduct, PharmacySale
from nanostore.routes import bp


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

    def test_every_store_mode_renders_its_interface(self):
        expected = {
            "pharmacy": "Operacao da farmacia", "store": "Painel da loja",
            "distributor": "Central de distribuicao", "commerce": "Gestao comercial",
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
                for marker in ("Entrada ou saida", "Separacao e entrega", "Notas dos pedidos", "Novo cliente"):
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


if __name__ == "__main__":
    unittest.main()
