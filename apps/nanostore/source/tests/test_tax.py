import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


SOURCE_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nanostore_tax", SOURCE_DIR / "nanostore" / "tax.py")
TAX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TAX)


def product(**overrides):
    values = {
        "sku": "MED-1", "name": "Produto", "ncm": "30049099", "cest": "",
        "cfop": "5102", "fiscal_origin": "0", "icms_cst": "102", "pis_cst": "49",
        "cofins_cst": "49", "tax_unit": "UN", "gtin_taxable": "SEM GTIN",
        "has_tax_benefit": False, "benefit_code": "", "anvisa_code": "ISENTO",
        "max_consumer_price": 10, "ibs_cbs_cst": "", "tax_classification": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TaxRulesTest(unittest.TestCase):
    def test_valid_cnpj_and_gtin(self):
        self.assertTrue(TAX.valid_cnpj("23.029.197/0001-97"))
        self.assertTrue(TAX.valid_gtin("7894900011517"))
        self.assertTrue(TAX.valid_gtin("SEM GTIN"))
        self.assertFalse(TAX.valid_gtin("123"))

    def test_medicine_requires_anvisa_and_pmc_for_nfe(self):
        errors = TAX.validate_product(product(anvisa_code="", max_consumer_price=0), "1", "55")
        self.assertTrue(any("ANVISA" in error for error in errors))
        self.assertTrue(any("preco maximo" in error for error in errors))

    def test_normal_regime_requires_ibs_cbs(self):
        item = product(icms_cst="00", ibs_cbs_cst="", tax_classification="")
        errors = TAX.validate_product(item, "3", "65")
        self.assertTrue(any("CST IBS/CBS" in error for error in errors))
        self.assertTrue(any("cClassTrib" in error for error in errors))

    def test_issuer_must_match_certificate(self):
        settings = {
            "FISCAL_LEGAL_NAME": "Resquetti", "FISCAL_CNPJ": "23029197000197",
            "FISCAL_IE": "1234567890", "FISCAL_UF": "PR", "FISCAL_CITY_CODE": "4106902",
            "FISCAL_CRT": "1",
        }
        self.assertEqual(TAX.validate_issuer(settings, "23029197000197"), [])
        self.assertTrue(any("certificado" in error for error in TAX.validate_issuer(settings, "11111111000191")))


if __name__ == "__main__":
    unittest.main()
