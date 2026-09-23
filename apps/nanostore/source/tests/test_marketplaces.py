import base64
import hashlib
import hmac
import json
import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from flask import Flask


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nanostore.extensions import db
from nanostore.marketplaces import marketplace_catalog, normalize_marketplace_provider
from nanostore.models import (
    FinancialEntry,
    MarketplaceAccount,
    MarketplaceOrderLink,
    MarketplaceProductMapping,
    MarketplaceSyncEvent,
    PharmacyLot,
    PharmacyPayment,
    PharmacyProduct,
    PharmacySale,
    Shipment,
    ShipmentEvent,
    ShipmentItem,
)
from nanostore.routes import bp


class MarketplaceHubTest(unittest.TestCase):
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
        self.admin_headers = {"X-Portal-Usuario-Perfil": "admin"}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def make_product(self, sku="LOCAL-1", stock="10", sale_price="15"):
        product = PharmacyProduct(
            sku=sku,
            name=f"Produto {sku}",
            sale_price=Decimal(sale_price),
            cost_price=Decimal("2"),
            tracks_inventory=True,
        )
        db.session.add(product)
        db.session.flush()
        db.session.add(PharmacyLot(
            product_id=product.id,
            lot_code=f"LOTE-{sku}",
            expiration_date=date(2030, 1, 1),
            received_at=date.today(),
            quantity_received=Decimal(stock),
            quantity_available=Decimal(stock),
            purchase_price=Decimal("2"),
        ))
        db.session.commit()
        return product

    def make_account(self, provider="mercado_livre", prefix="TESTSHOP", enabled=True):
        account = MarketplaceAccount(
            provider=provider,
            name="Loja principal",
            credential_env_prefix=prefix,
            enabled=enabled,
            status="ready" if enabled else "disabled",
            sync_orders=True,
            sync_inventory=True,
            sync_logistics=True,
        )
        db.session.add(account)
        db.session.commit()
        return account

    def map_product(self, account, product, external_id="EXT-1", external_sku="CANAL-1"):
        mapping = MarketplaceProductMapping(
            account_id=account.id,
            product_id=product.id,
            external_product_id=external_id,
            external_sku=external_sku,
        )
        db.session.add(mapping)
        db.session.commit()
        return mapping

    @staticmethod
    def canonical_payload(external_id="ORDER-1", product_id="EXT-1"):
        return {
            "event": "order.created",
            "order": {
                "id": external_id,
                "status": "approved",
                "payment_status": "paid",
                "customer": {"name": "Cliente Canal", "phone": "41999999999"},
                "shipping": {
                    "address": "Rua Central, 10",
                    "city": "Curitiba",
                    "state": "PR",
                    "postal_code": "80000000",
                },
                "items": [{
                    "external_product_id": product_id,
                    "sku": "CANAL-1",
                    "quantity": 2,
                    "unit_price": 15,
                }],
            },
        }

    def signed_relay_headers(self, payload, event_id="EVENT-1", secret="secret-123"):
        raw = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return raw, {
            "Content-Type": "application/json",
            "X-NanoStore-Event-Id": event_id,
            "X-NanoStore-Signature": f"sha256={signature}",
        }

    def test_catalog_covers_requested_channels_and_aliases(self):
        providers = {item["provider"] for item in marketplace_catalog()}
        self.assertEqual("woocommerce", normalize_marketplace_provider("WordPress"))
        self.assertEqual("aiqfome", normalize_marketplace_provider("iqfome"))
        self.assertEqual("magalu", normalize_marketplace_provider("Magazine Luiza"))
        self.assertTrue({
            "woocommerce", "shopee", "mercado_livre", "ifood", "aiqfome", "magalu",
            "amazon", "facebook_marketplace", "whatsapp", "aliexpress", "olx", "ebay",
        }.issubset(providers))

    def test_account_configuration_requires_admin_and_keeps_secrets_out_of_payload(self):
        payload = {
            "provider": "mercado_livre",
            "name": "Seller ML",
            "seller_id": "SELLER-1",
            "credential_env_prefix": "NANOSTORE_ML_SELLER1",
            "enabled": True,
            "sync_orders": True,
            "sync_inventory": True,
            "sync_logistics": True,
        }
        forbidden = self.client.post(
            "/api/marketplaces/accounts", json=payload,
            headers={"X-Portal-Usuario-Perfil": "usuario"},
        )
        self.assertEqual(403, forbidden.status_code)

        response = self.client.post("/api/marketplaces/accounts", json=payload, headers=self.admin_headers)
        self.assertEqual(201, response.status_code, response.get_json())
        account = response.get_json()["account"]
        self.assertEqual("pending", account["status"])
        self.assertFalse(account["credentials_configured"])
        self.assertNotIn("secret", account)

    def test_channel_capabilities_prevent_unsupported_olx_stock_and_logistics_sync(self):
        response = self.client.post("/api/marketplaces/accounts", json={
            "provider": "olx",
            "name": "Classificados",
            "credential_env_prefix": "NANOSTORE_OLX",
            "sync_orders": True,
            "sync_inventory": True,
            "sync_logistics": True,
        }, headers=self.admin_headers)
        self.assertEqual(201, response.status_code, response.get_json())
        account = response.get_json()["account"]
        self.assertFalse(account["sync_orders"])
        self.assertFalse(account["sync_inventory"])
        self.assertFalse(account["sync_logistics"])

    def test_signed_order_is_idempotent_and_updates_stock_finance_and_logistics(self):
        account = self.make_account()
        product = self.make_product()
        self.map_product(account, product)
        payload = self.canonical_payload()
        raw, headers = self.signed_relay_headers(payload)

        with patch.dict(os.environ, {"TESTSHOP_WEBHOOK_SECRET": "secret-123"}):
            first = self.client.post(
                f"/api/marketplaces/accounts/{account.id}/webhook", data=raw, headers=headers
            )
            second = self.client.post(
                f"/api/marketplaces/accounts/{account.id}/webhook", data=raw, headers=headers
            )

        self.assertEqual(201, first.status_code, first.get_json())
        self.assertEqual(200, second.status_code, second.get_json())
        self.assertTrue(second.get_json()["duplicate"])
        self.assertEqual(1, PharmacySale.query.count())
        self.assertEqual(1, MarketplaceOrderLink.query.count())
        self.assertEqual(1, MarketplaceSyncEvent.query.count())
        self.assertEqual(1, PharmacyPayment.query.count())
        self.assertEqual("paid", FinancialEntry.query.one().status)
        lot = PharmacyLot.query.filter_by(product_id=product.id).one()
        self.assertEqual(Decimal("8.000"), lot.quantity_available)
        sale = PharmacySale.query.one()
        self.assertEqual("mercado_livre", sale.source_channel)
        self.assertEqual("delivery", sale.fulfillment_type)
        self.assertEqual("Rua Central, 10", sale.delivery_address)

    def test_unmapped_order_is_blocked_without_partial_sale_or_stock_change(self):
        account = self.make_account()
        product = self.make_product()
        payload = self.canonical_payload(product_id="UNKNOWN")
        raw, headers = self.signed_relay_headers(payload)

        with patch.dict(os.environ, {"TESTSHOP_WEBHOOK_SECRET": "secret-123"}):
            response = self.client.post(
                f"/api/marketplaces/accounts/{account.id}/webhook", data=raw, headers=headers
            )

        self.assertEqual(422, response.status_code, response.get_json())
        self.assertEqual(0, PharmacySale.query.count())
        self.assertEqual("blocked", MarketplaceSyncEvent.query.one().status)
        self.assertEqual(Decimal("10.000"), PharmacyLot.query.filter_by(product_id=product.id).one().quantity_available)

    def test_new_event_for_existing_order_updates_logistics_without_second_stock_exit(self):
        account = self.make_account()
        product = self.make_product()
        self.map_product(account, product)
        first_payload = self.canonical_payload()
        first_raw, first_headers = self.signed_relay_headers(first_payload, event_id="EVENT-FIRST")
        second_payload = self.canonical_payload()
        second_payload["order"]["logistics_status"] = "shipped"
        second_payload["order"]["shipping"].update({
            "carrier": "correios",
            "tracking_code": "AA123456789BR",
            "service_code": "03220",
            "estimated_delivery_date": "2026-09-10",
        })
        second_raw, second_headers = self.signed_relay_headers(second_payload, event_id="EVENT-SHIPPED")

        with patch.dict(os.environ, {"TESTSHOP_WEBHOOK_SECRET": "secret-123"}):
            first = self.client.post(
                f"/api/marketplaces/accounts/{account.id}/webhook", data=first_raw, headers=first_headers
            )
            second = self.client.post(
                f"/api/marketplaces/accounts/{account.id}/webhook", data=second_raw, headers=second_headers
            )

        self.assertEqual(201, first.status_code, first.get_json())
        self.assertEqual(200, second.status_code, second.get_json())
        self.assertFalse(second.get_json()["created"])
        self.assertEqual("out_for_delivery", PharmacySale.query.one().delivery_status)
        self.assertEqual(2, MarketplaceSyncEvent.query.count())
        self.assertEqual(Decimal("8.000"), PharmacyLot.query.filter_by(product_id=product.id).one().quantity_available)
        shipment = Shipment.query.one()
        self.assertEqual("correios", shipment.carrier)
        self.assertEqual("AA123456789BR", shipment.tracking_code)
        self.assertEqual("in_transit", shipment.status)
        self.assertEqual(date(2026, 9, 10), shipment.estimated_delivery_date)
        self.assertEqual(Decimal("2.000"), ShipmentItem.query.one().quantity)
        self.assertEqual("mercado_livre", ShipmentEvent.query.one().source)

    def test_invalid_signature_is_rejected(self):
        account = self.make_account()
        payload = self.canonical_payload()
        raw = json.dumps(payload).encode()
        with patch.dict(os.environ, {"TESTSHOP_WEBHOOK_SECRET": "secret-123"}):
            response = self.client.post(
                f"/api/marketplaces/accounts/{account.id}/webhook",
                data=raw,
                headers={"Content-Type": "application/json", "X-NanoStore-Signature": "sha256=invalid"},
            )
        self.assertEqual(401, response.status_code)
        self.assertEqual(0, MarketplaceSyncEvent.query.count())

    def test_native_woocommerce_signature_and_payload_are_supported(self):
        account = self.make_account(provider="woocommerce", prefix="TESTWOO")
        product = self.make_product()
        self.map_product(account, product, external_id="321", external_sku="LOCAL-1")
        payload = {
            "id": 9001,
            "status": "processing",
            "date_paid": "2026-09-02T10:00:00",
            "billing": {"first_name": "Maria", "last_name": "Silva", "phone": "41999999999"},
            "shipping": {"address_1": "Rua Woo", "number": "20", "city": "Curitiba", "state": "PR"},
            "line_items": [{
                "product_id": 321, "sku": "LOCAL-1", "quantity": 1, "subtotal": "15.00", "total": "15.00",
            }],
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        signature = base64.b64encode(hmac.new(b"woo-secret", raw, hashlib.sha256).digest()).decode()
        with patch.dict(os.environ, {"TESTWOO_WEBHOOK_SECRET": "woo-secret"}):
            response = self.client.post(
                f"/api/marketplaces/accounts/{account.id}/webhook",
                data=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-WC-Webhook-Signature": signature,
                    "X-WC-Webhook-Delivery-ID": "WOO-EVENT-1",
                    "X-WC-Webhook-Topic": "order.created",
                },
            )
        self.assertEqual(201, response.status_code, response.get_json())
        self.assertEqual("Maria Silva", PharmacySale.query.one().customer_name)

    def test_inventory_queue_is_auditable_and_does_not_duplicate_same_balance(self):
        account = self.make_account()
        product = self.make_product(stock="7")
        self.map_product(account, product)
        first = self.client.post(
            "/api/marketplaces/inventory/queue", json={"account_id": account.id}, headers=self.admin_headers
        )
        second = self.client.post(
            "/api/marketplaces/inventory/queue", json={"account_id": account.id}, headers=self.admin_headers
        )
        self.assertEqual(1, first.get_json()["queued"])
        self.assertEqual(0, second.get_json()["queued"])
        event = MarketplaceSyncEvent.query.one()
        self.assertEqual("outbound", event.direction)
        self.assertEqual("pending", event.status)
        self.assertIn('"quantity": "7.000"', event.payload_json)


if __name__ == "__main__":
    unittest.main()
