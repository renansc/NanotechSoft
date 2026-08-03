import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID


SOURCE_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nanostore_fiscal", SOURCE_DIR / "nanostore" / "fiscal.py")
FISCAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FISCAL)
build_signed_simulation = FISCAL.build_signed_simulation
load_fiscal_identity = FISCAL.load_fiscal_identity


class FiscalSimulatorTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.password = "teste-seguro"
        self.certificate_path = Path(self.temp_dir.name) / "emitente.pfx"
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "EMPRESA TESTE LTDA:12345678000195")]
        )
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=400))
            .not_valid_after(now - timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        payload = pkcs12.serialize_key_and_certificates(
            b"simulador",
            key,
            certificate,
            None,
            serialization.BestAvailableEncryption(self.password.encode()),
        )
        self.certificate_path.write_bytes(payload)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_expired_certificate_signs_local_simulation(self):
        identity = load_fiscal_identity(self.certificate_path, self.password)
        self.assertTrue(identity["expired"])
        self.assertEqual(identity["cnpj"], "12345678000195")

        result = build_signed_simulation(
            {
                "code": "VENDA-1",
                "customer_name": "Consumidor Teste",
                "source_channel": "balcao",
                "subtotal_amount": "12.50",
                "discount_amount": "0.50",
                "total_amount": "12.00",
                "items": [
                    {
                        "sku": "ABC-1",
                        "product_name": "Produto & Teste",
                        "lot_code": "L1",
                        "quantity": "1",
                        "unit_price": "12.50",
                        "discount_amount": "0.50",
                        "total_amount": "12.00",
                    }
                ],
            },
            "65",
            identity=identity,
        )

        self.assertEqual(result["status"], "signed_expired_certificate")
        self.assertIn('semValorFiscal="true"', result["xml"])
        self.assertIn('verificada="true"', result["xml"])
        self.assertIn("Produto &amp; Teste", result["xml"])

    def test_rejects_unknown_document_model(self):
        identity = load_fiscal_identity(self.certificate_path, self.password)
        with self.assertRaisesRegex(ValueError, "55 ou 65"):
            build_signed_simulation({"items": [{}]}, "99", identity=identity)


if __name__ == "__main__":
    unittest.main()
