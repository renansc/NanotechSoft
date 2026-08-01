import os
import unittest

from vendas_diario import parse_report, read_report


class VendasDiarioParserTest(unittest.TestCase):
    def test_parses_two_column_items_and_negative_order(self):
        text = """
    BEBIDAS WHITE RIVER LTDA                                   31/07/26  10 18     1
                        CONFERENCIA DE PEDIDOS            VENDEDOR     6
    Codigo Tb Vg  Qua Un Descricao                    Valor Total I* Codigo Tb Vg  Qua Un Descricao                    Valor Total I*
      659 ELIAS MAFORTE MEIRELES         PADARIA TALISMA                JD.INTERLAGOS        =>LIVRE        <=
      7000  1  6      4 PT GUARANA RIO BRANCO PET 6X2       34.90      7500 91  6      1 PT ABACAXI RIO BRANCO PET 6X2       34.90
                                       TOTAL DO PEDIDO     174.50                                      PESO BRUTO TOTAL      65.00Kg
    -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
      662 W. C. CINTRA ACOUGUE - ME      CASA DE CARNE FRIVALE          JD. PETROPOLIS       =>LIVRE        <=
    Venda Neg. Motivo : 01 = ESTOCADO
    -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
        """
        parsed = parse_report(text, "modelo.txt")
        self.assertEqual("2026-07-31", parsed["data_ref"])
        self.assertEqual(2, len(parsed["orders"]))
        self.assertEqual(2, len(parsed["orders"][0]["items"]))
        self.assertEqual(91, parsed["orders"][0]["items"][1]["tabela"])
        self.assertEqual("negativa", parsed["orders"][1]["status"])
        self.assertEqual("ESTOCADO", parsed["orders"][1]["motivo"])

    def test_attached_model_is_supported_when_available(self):
        path = "/home/renan/Downloads/10190016.txt"
        if not os.path.exists(path):
            self.skipTest("arquivo de exemplo nao disponivel")
        text, signature = read_report(path)
        parsed = parse_report(text, os.path.basename(path))
        self.assertEqual(64, len(signature))
        self.assertEqual("2026-07-31", parsed["data_ref"])
        self.assertGreater(len(parsed["orders"]), 300)
        self.assertGreater(sum(len(order["items"]) for order in parsed["orders"]), 200)


if __name__ == "__main__":
    unittest.main()
