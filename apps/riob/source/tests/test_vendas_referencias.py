import unittest
from unittest import mock

from vendas_referencias import (
    classificar_etapa_conciliacao,
    mapas_carga_equivalentes,
    normalizar_cliente,
    parse_rotas_pdf,
)


class VendasReferenciasTest(unittest.TestCase):
    def test_normaliza_cliente_com_rota_endereco_e_vendedor(self):
        cliente = normalizar_cliente({
            "CODIGO": "00014",
            "ROTA": "00514",
            "CGC": "00.089.921/7399-72",
            "RUA": "AV JOAO T.M.S. NETO",
            "NR": "706",
            "CIDADE": "MOREIRA SALES",
            "UF": "PR",
            "CEP": "87.370-000",
            "BAIRRO": "CENTRO",
            "VENDEDOR": "015-MARCOS LEANDRO",
        })

        self.assertEqual("00014", cliente["codigo"])
        self.assertEqual("514", cliente["rota_codigo"])
        self.assertEqual("AV JOAO T.M.S. NETO, 706", cliente["endereco"])
        self.assertEqual("15", cliente["vendedor_codigo"])
        self.assertEqual("MARCOS LEANDRO", cliente["vendedor_nome"])

    @mock.patch("vendas_referencias._pdf_reader")
    def test_parseia_tabela_de_rotas_pdf(self, reader_mock):
        reader_mock.return_value.pages = [mock.Mock(extract_text=mock.Mock(return_value=(
            "Cod Rota        Rota\n"
            "502             ATALAIA/FLORIDA/LOBATO\n"
            "521             ASTORGA\n"
            "powered by CTA Sistemas\n"
        )))]

        rotas = parse_rotas_pdf("rotas.pdf")

        self.assertEqual([
            {"codigo": "502", "descricao": "ATALAIA/FLORIDA/LOBATO"},
            {"codigo": "521", "descricao": "ASTORGA"},
        ], rotas)

    def test_classifica_os_tres_estados_sem_ocultar_divergencias(self):
        self.assertEqual(1, classificar_etapa_conciliacao(tem_txt=True)["etapa"])
        self.assertEqual(2, classificar_etapa_conciliacao(tem_txt=True, tem_pdf=True)["etapa"])
        final = classificar_etapa_conciliacao(
            tem_txt=True, tem_pdf=True, tem_sellout=True,
            divergencias=[{"campo": "valor_bruto"}],
        )
        self.assertEqual(3, final["etapa"])
        self.assertEqual("sellout_com_divergencias", final["status"])

    def test_reconhece_mapas_pdf_e_sellout_da_mesma_carga(self):
        self.assertTrue(mapas_carga_equivalentes("160401", "7310401", "16"))
        self.assertTrue(mapas_carga_equivalentes("081101", "7181101", "8"))
        self.assertFalse(mapas_carga_equivalentes("080601", "7560501", "8"))
        self.assertFalse(mapas_carga_equivalentes("160401", "7310401, 7510401", "16"))
        self.assertFalse(mapas_carga_equivalentes("150401", "7310401", "16"))


if __name__ == "__main__":
    unittest.main()
