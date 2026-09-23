import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from flask import Flask


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nanostore.extensions import db
from nanostore.models import (
    PharmacyCustomer,
    PharmacyProduct,
    PharmacySale,
    PharmacySaleItem,
    Shipment,
    ShipmentEvent,
    ShipmentItem,
)
from nanostore.routes import bp


class ShipmentTrackingTest(unittest.TestCase):
    def setUp(self):
        source_dir = Path(__file__).resolve().parents[1] / "nanostore"
        self.app = Flask(
            __name__, template_folder=str(source_dir / "templates"), static_folder=str(source_dir / "static")
        )
        self.app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", TESTING=True)
        db.init_app(self.app)
        self.app.register_blueprint(bp)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def make_sale(self, quantity="3"):
        customer = PharmacyCustomer(
            name="Cliente Entrega", phone="41999999999", address="Rua Central",
            city="Curitiba", state="PR", postal_code="80000-000",
        )
        product = PharmacyProduct(
            sku="RASTREIO-1", name="Produto rastreavel", sale_price=Decimal("15"),
            cost_price=Decimal("2"), tracks_inventory=True,
        )
        db.session.add_all([customer, product])
        db.session.flush()
        sale = PharmacySale(
            code="PED-RASTREIO", customer_name=customer.name, customer_phone=customer.phone,
            customer_id=customer.id, fulfillment_type="delivery", delivery_address="Rua Central",
            delivery_status="new", total_amount=Decimal("45"),
        )
        db.session.add(sale)
        db.session.flush()
        item = PharmacySaleItem(
            sale_id=sale.id, product_id=product.id, quantity=Decimal(quantity),
            unit_price=Decimal("15"), total_amount=Decimal("45"),
        )
        db.session.add(item)
        db.session.commit()
        return sale, item

    def test_creates_product_trace_and_uses_customer_postal_code(self):
        sale, item = self.make_sale()
        response = self.client.post("/api/shipments", json={
            "sale_id": sale.id,
            "carrier": "correios",
            "tracking_code": "AA123456789BR",
            "service_code": "SERVICO",
            "origin_postal_code": "01001-000",
            "estimated_delivery_date": "2026-09-08",
        })
        self.assertEqual(201, response.status_code, response.get_json())
        shipment = Shipment.query.one()
        self.assertEqual("80000000", shipment.destination_postal_code)
        self.assertEqual(date(2026, 9, 8), shipment.estimated_delivery_date)
        self.assertEqual(item.id, ShipmentItem.query.one().sale_item_id)
        self.assertEqual(Decimal("3.000"), ShipmentItem.query.one().quantity)
        self.assertEqual("ready", PharmacySale.query.one().delivery_status)
        self.assertEqual(1, ShipmentEvent.query.count())

    def test_supports_split_shipments_without_overallocating_product(self):
        sale, item = self.make_sale()
        first = self.client.post("/api/shipments", json={
            "sale_id": sale.id,
            "carrier": "transportadora",
            "items": [{"sale_item_id": item.id, "quantity": 1}],
        })
        second = self.client.post("/api/shipments", json={
            "sale_id": sale.id,
            "carrier": "transportadora",
            "items": [{"sale_item_id": item.id, "quantity": 2}],
        })
        excess = self.client.post("/api/shipments", json={
            "sale_id": sale.id,
            "carrier": "transportadora",
            "items": [{"sale_item_id": item.id, "quantity": 1}],
        })
        self.assertEqual(201, first.status_code, first.get_json())
        self.assertEqual(201, second.status_code, second.get_json())
        self.assertEqual(400, excess.status_code, excess.get_json())
        self.assertEqual(2, Shipment.query.count())

    def test_rejects_invalid_correios_tracking_code(self):
        sale, _ = self.make_sale()
        response = self.client.post("/api/shipments", json={
            "sale_id": sale.id, "carrier": "correios", "tracking_code": "INVALIDO",
        })
        self.assertEqual(400, response.status_code)
        self.assertEqual(0, Shipment.query.count())

    def test_refresh_deduplicates_correios_events_and_updates_order(self):
        sale, _ = self.make_sale()
        created = self.client.post("/api/shipments", json={
            "sale_id": sale.id,
            "carrier": "correios",
            "tracking_code": "AA123456789BR",
        })
        shipment_id = created.get_json()["shipment"]["id"]

        class FakeClient:
            def track(self, _code):
                return {"events": [{
                    "code": "BDE",
                    "description": "Objeto entregue ao destinatario",
                    "location": "Curitiba, PR",
                    "occurred_at": "2026-09-05T17:30:00Z",
                    "raw": {"codigo": "BDE"},
                }]}

            def estimate_delivery(self, *_args):
                raise AssertionError("Nao deve consultar prazo sem servico")

        with patch("nanostore.routes.CorreiosClient", return_value=FakeClient()):
            first = self.client.post(f"/api/shipments/{shipment_id}/refresh", json={})
            second = self.client.post(f"/api/shipments/{shipment_id}/refresh", json={})

        self.assertEqual(200, first.status_code, first.get_json())
        self.assertEqual(1, first.get_json()["new_events"])
        self.assertEqual(0, second.get_json()["new_events"])
        self.assertEqual("delivered", Shipment.query.one().status)
        self.assertEqual("delivered", PharmacySale.query.one().delivery_status)
        self.assertEqual(2, ShipmentEvent.query.count())

    def test_product_trace_searches_by_sku(self):
        sale, _ = self.make_sale()
        self.client.post("/api/shipments", json={"sale_id": sale.id, "carrier": "transportadora"})
        response = self.client.get("/api/shipments?q=RASTREIO-1")
        self.assertEqual(200, response.status_code, response.get_json())
        self.assertEqual(1, len(response.get_json()["shipments"]))
        self.assertEqual("RASTREIO-1", response.get_json()["shipments"][0]["items"][0]["sku"])

    def test_estimate_endpoint_uses_correios_client(self):
        fake = type("FakeClient", (), {
            "estimate_delivery": lambda self, postal, service: {
                "destination_postal_code": postal,
                "service_code": service,
                "estimated_delivery_date": "2026-09-08",
            }
        })()
        with patch("nanostore.routes.CorreiosClient", return_value=fake):
            response = self.client.post("/api/shipping/correios/estimate", json={
                "destination_postal_code": "80000000", "service_code": "SERVICO",
            })
        self.assertEqual(200, response.status_code, response.get_json())
        self.assertEqual("2026-09-08", response.get_json()["estimate"]["estimated_delivery_date"])


if __name__ == "__main__":
    unittest.main()
