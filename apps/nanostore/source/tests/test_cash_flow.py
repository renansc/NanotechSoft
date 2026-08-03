import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nanostore.extensions import db
from nanostore.models import CashSession, FinancialEntry, PharmacyLot, PharmacyPayment, PharmacyProduct, PharmacySale
from nanostore.routes import bp


class CashFlowTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
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


if __name__ == "__main__":
    unittest.main()
