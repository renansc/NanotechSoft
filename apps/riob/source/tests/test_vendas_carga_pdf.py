import os
import unittest

from vendas_carga_pdf import parse_carga_pdf


class VendasCargaPdfTest(unittest.TestCase):
    def test_parses_attached_load_model(self):
        path = "/home/renan/Downloads/310726 marcos leandro.pdf"
        if not os.path.exists(path):
            self.skipTest("PDF de exemplo nao disponivel")
        carga = parse_carga_pdf(path)
        self.assertEqual("153101", carga["mapa"])
        self.assertEqual("514", carga["rota_codigo"])
        self.assertEqual("2026-07-31", carga["data_ref"])
        self.assertEqual(3, len(carga["cidades"]))
        self.assertEqual(16, len(carga["produtos"]))
        self.assertEqual(9, carga["qtd_entregas"])
        self.assertAlmostEqual(74, carga["volumes_total"])
        self.assertAlmostEqual(1157.5, carga["peso_total"])
        self.assertAlmostEqual(2102.82, carga["valor_total"])


if __name__ == "__main__":
    unittest.main()
