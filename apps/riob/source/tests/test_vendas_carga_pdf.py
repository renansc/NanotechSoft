import os
import unittest
from unittest import mock

from vendas_carga_pdf import parse_carga_pdf, parse_cargas_pdf


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

    @mock.patch("vendas_carga_pdf.PdfReader")
    @mock.patch("builtins.open", new_callable=mock.mock_open, read_data=b"pdf-test")
    def test_parses_each_pdf_page_as_an_independent_load(self, _open, reader_mock):
        def page_text(map_number, route, total):
            return (
                "terca-feira, 4 de agosto de 2026\n"
                f"Mapa: {map_number} [MAPA NAO ASSOCIADO] Placa: Rota: {route} - ROTA TESTE  \n"
                "Grupo C.: PET 2LT\n"
                "7000      GUARANA TESTE 6X2LT                                      10 PT\n"
                "Numero Entregas: 1\n"
                f"Valor Total Liquido: {total}\n"
                "Peso Total: 100,000\n"
            )

        reader_mock.return_value.pages = [
            mock.Mock(extract_text=mock.Mock(return_value=page_text("060401", "521", "100,00"))),
            mock.Mock(extract_text=mock.Mock(return_value=page_text("070401", "522", "200,00"))),
        ]

        cargas = parse_cargas_pdf("cargas.pdf")

        self.assertEqual(["060401", "070401"], [carga["mapa"] for carga in cargas])
        self.assertEqual([1, 2], [carga["pagina"] for carga in cargas])
        self.assertEqual([100.0, 200.0], [carga["valor_total"] for carga in cargas])
        self.assertNotEqual(cargas[0]["assinatura"], cargas[1]["assinatura"])


if __name__ == "__main__":
    unittest.main()
