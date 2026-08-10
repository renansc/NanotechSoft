import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from nanostore.fiscal import load_fiscal_identity
from nanostore.nfe import DS_NS, NFE_NS, access_key_check_digit, build_homologation_nfe


class NFeHomologationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.password = "senha-teste"
        self.certificate_path = Path(self.temp_dir.name) / "emitente.pfx"
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "TRANSP DIST BEB RESQUETTI LTDA:23029197000197")
        ])
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(self.key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30))
            .sign(self.key, hashes.SHA256())
        )
        self.certificate_path.write_bytes(pkcs12.serialize_key_and_certificates(
            b"nfe", self.key, certificate, None,
            serialization.BestAvailableEncryption(self.password.encode()),
        ))
        self.identity = load_fiscal_identity(self.certificate_path, self.password)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _payload(self):
        return {
            "code": "NS-TESTE-1",
            "total_amount": "35.00",
            "issuer": {
                "FISCAL_LEGAL_NAME": "TRANSP DIST BEB RESQUETTI LTDA",
                "FISCAL_CNPJ": "23029197000197",
                "FISCAL_IE": "9086419308",
                "FISCAL_CRT": "1",
                "FISCAL_ADDRESS": "RUA PAUL PERCY HARRIS",
                "FISCAL_ADDRESS_NUMBER": "971-SL01",
                "FISCAL_NEIGHBORHOOD": "PQ RESQUETTI",
                "FISCAL_CITY": "ASTORGA",
                "FISCAL_CITY_CODE": "4102109",
                "FISCAL_UF": "PR",
                "FISCAL_POSTAL_CODE": "86730000",
                "FISCAL_PHONE": "4432343344",
            },
            "customer": {
                "name": "Cliente Teste",
                "document": "52998224725",
                "phone": "44999999999",
                "address": "RUA ANTONIO FIORENTINI",
                "address_number": "38",
                "neighborhood": "JARDIM ITALIA",
                "city": "ASTORGA",
                "city_code": "4102109",
                "state": "PR",
                "postal_code": "86730000",
                "state_registration_indicator": "9",
                "state_registration": "",
            },
            "items": [{
                "sku": "TEST-GELO", "product_name": "Gelo", "barcode": "", "unit": "UN",
                "quantity": "1", "unit_price": "35", "discount_amount": "0", "total_amount": "35",
                "ncm": "22019000", "cest": "", "cfop": "5102", "origin": "0", "icms_cst": "102",
                "pis_cst": "49", "cofins_cst": "49", "tax_unit": "UN", "gtin_taxable": "SEM GTIN",
            }],
        }

    def test_builds_access_key_and_valid_xml_signature(self):
        issued_at = datetime(2026, 8, 6, 12, 30, tzinfo=timezone(timedelta(hours=-3)))
        result = build_homologation_nfe(
            self._payload(), series=1, number=1, identity=self.identity,
            issued_at=issued_at, numeric_code=12345678,
        )
        self.assertEqual(len(result["access_key"]), 44)
        self.assertEqual(int(result["access_key"][-1]), access_key_check_digit(result["access_key"][:-1]))

        root = etree.fromstring(result["xml"].encode())
        namespace = {"nfe": NFE_NS, "ds": DS_NS}
        self.assertEqual(root.xpath("string(nfe:infNFe/nfe:ide/nfe:tpAmb)", namespaces=namespace), "2")
        self.assertEqual(root.xpath("string(nfe:infNFe/nfe:ide/nfe:mod)", namespaces=namespace), "55")
        self.assertEqual(
            root.xpath("string(nfe:infNFe/nfe:dest/nfe:xNome)", namespaces=namespace),
            "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL",
        )

        signed_info = root.find(f"{{{DS_NS}}}Signature/{{{DS_NS}}}SignedInfo")
        signature_value = root.findtext(f"{{{DS_NS}}}Signature/{{{DS_NS}}}SignatureValue")
        import base64
        self.key.public_key().verify(
            base64.b64decode(signature_value),
            etree.tostring(signed_info, method="c14n", exclusive=False, with_comments=False),
            padding.PKCS1v15(), hashes.SHA1(),
        )

    def test_rejects_unsupported_tax_profile(self):
        payload = self._payload()
        payload["items"][0]["icms_cst"] = "400"
        with self.assertRaisesRegex(ValueError, "CSOSN 102 ou 500"):
            build_homologation_nfe(payload, series=1, number=2, identity=self.identity)

    def test_builds_csosn_500_used_by_riob(self):
        payload = self._payload()
        payload["items"][0]["icms_cst"] = "500"
        result = build_homologation_nfe(payload, series=1, number=2, identity=self.identity)
        root = etree.fromstring(result["xml"].encode())
        namespace = {"nfe": NFE_NS}
        self.assertEqual(root.xpath("string(.//nfe:ICMSSN500/nfe:CSOSN)", namespaces=namespace), "500")

    def test_rejects_expired_certificate(self):
        self.identity["valid_now"] = False
        with self.assertRaisesRegex(RuntimeError, "Certificado A1 vencido"):
            build_homologation_nfe(self._payload(), series=1, number=3, identity=self.identity)


if __name__ == "__main__":
    unittest.main()
