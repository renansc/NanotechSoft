import datetime
import unittest
from pathlib import Path
from unittest import mock

import server

SOURCE_DIR = Path(__file__).resolve().parents[1]


class FrotaRelatorioMensalTests(unittest.TestCase):
    def test_dashboard_exibe_rodagem_total_e_media_geral_ponderada(self):
        class Cursor:
            def __init__(self):
                self.rows = []
                self.row = None

            def execute(self, sql, params=None):
                normalized = " ".join(sql.split()).lower()
                self.row = None
                if normalized.startswith("show tables"):
                    self.rows = []
                elif "from veiculos" in normalized:
                    self.rows = [{
                        "id": 10, "nome": "Caminhao 10", "placa": "ABC-1010",
                        "modelo": "Truck", "km_atual": 2100,
                        "intervalo_manut_km": 10000, "intervalo_oleo_km": 5000,
                    }]
                elif "from abastecimentos" in normalized:
                    self.rows = [
                        {"id": 1, "veiculo_id": 10, "km": 1000, "quantidade_litros": 100, "combustivel_tipo": "diesel_s10", "status": "abastecido"},
                        {"id": 2, "veiculo_id": 10, "km": 1500, "quantidade_litros": 100, "combustivel_tipo": "diesel_s10", "status": "abastecido"},
                        {"id": 3, "veiculo_id": 10, "km": 1600, "quantidade_litros": 20, "combustivel_tipo": "arla", "status": "abastecido"},
                        {"id": 4, "veiculo_id": 10, "km": 2100, "quantidade_litros": 200, "combustivel_tipo": "diesel_s10", "status": "abastecido"},
                    ]
                else:
                    self.rows = []

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.row

            def close(self):
                pass

        class Connection:
            def cursor(self, dictionary=False):
                return Cursor()

            def close(self):
                pass

        with server.app.test_request_context("/api/dashboard_frota"), \
             mock.patch.object(server, "get_conn", return_value=Connection()):
            payload = server.dashboard_frota().get_json()

        self.assertEqual(1100, payload[0]["km_total_rodado"])
        self.assertAlmostEqual(1100 / 300, payload[0]["media_km"], places=6)

    def test_media_ponderada_usa_base_anterior_e_ignora_arla(self):
        rows = [
            {
                "id": 1, "veiculo_id": 10, "veiculo_nome": "Caminhao 10",
                "placa": "ABC-1010", "km": 1000, "quantidade_litros": 100,
                "valor": 600, "status": "abastecido", "combustivel_tipo": "diesel_s10",
                "data_evento": datetime.datetime(2026, 8, 28, 8, 0), "posto": "Posto A",
            },
            {
                "id": 2, "veiculo_id": 10, "veiculo_nome": "Caminhao 10",
                "placa": "ABC-1010", "km": 1500, "quantidade_litros": 100,
                "valor": 650, "status": "abastecido", "combustivel_tipo": "diesel_s10",
                "data_evento": datetime.datetime(2026, 9, 5, 8, 0), "posto": "Posto A",
            },
            {
                "id": 3, "veiculo_id": 10, "veiculo_nome": "Caminhao 10",
                "placa": "ABC-1010", "km": 1600, "quantidade_litros": 20,
                "valor": 80, "status": "abastecido", "combustivel_tipo": "arla",
                "data_evento": datetime.datetime(2026, 9, 10, 8, 0), "posto": "Posto B",
            },
            {
                "id": 4, "veiculo_id": 10, "veiculo_nome": "Caminhao 10",
                "placa": "ABC-1010", "km": 2100, "quantidade_litros": 120,
                "valor": 780, "status": "abastecido", "combustivel_tipo": "diesel_s10",
                "data_evento": datetime.datetime(2026, 9, 20, 8, 0), "posto": "Posto B",
            },
        ]

        payload = server._montar_frota_relatorio_mensal(
            rows,
            mes="2026-09",
            veiculos=[{"id": 10, "nome": "Caminhao 10", "placa": "ABC-1010"}],
        )

        self.assertEqual(3, payload["resumo"]["abastecimentos"])
        self.assertEqual(240.0, payload["resumo"]["litros"])
        self.assertEqual(1510.0, payload["resumo"]["valor"])
        self.assertEqual(1100, payload["resumo"]["km_rodado"])
        self.assertEqual(5.0, payload["resumo"]["media_km_l"])
        self.assertIsNone(next(item for item in payload["abastecimentos"] if item["id"] == 3)["media_km_l"])
        self.assertEqual(1000, next(item for item in payload["abastecimentos"] if item["id"] == 2)["km_inicial"])

    def test_mes_invalido_e_rejeitado(self):
        with self.assertRaisesRegex(ValueError, "Mês inválido"):
            server._montar_frota_relatorio_mensal([], mes="2026-13")

    def test_consumo_rodagem_restringe_combustiveis_e_separa_arla(self):
        rows = [
            {
                "id": 1, "veiculo_id": 10, "veiculo_nome": "Caminhao 10",
                "placa": "ABC-1010", "km": 1000, "quantidade_litros": 100,
                "status": "abastecido", "combustivel_tipo": "diesel_s10",
                "data_evento": datetime.datetime(2026, 8, 28, 8, 0),
            },
            {
                "id": 2, "veiculo_id": 10, "veiculo_nome": "Caminhao 10",
                "placa": "ABC-1010", "km": 1500, "quantidade_litros": 100,
                "status": "abastecido", "combustivel_tipo": "diesel_s10",
                "data_evento": datetime.datetime(2026, 9, 5, 8, 0),
            },
            {
                "id": 3, "veiculo_id": 10, "veiculo_nome": "Caminhao 10",
                "placa": "ABC-1010", "km": 1600, "quantidade_litros": 20,
                "status": "abastecido", "combustivel_tipo": "arla",
                "data_evento": datetime.datetime(2026, 9, 10, 8, 0),
            },
            {
                "id": 4, "veiculo_id": 10, "veiculo_nome": "Caminhao 10",
                "placa": "ABC-1010", "km": 2100, "quantidade_litros": 120,
                "status": "abastecido", "combustivel_tipo": "diesel_s10",
                "data_evento": datetime.datetime(2026, 9, 20, 8, 0),
            },
            {
                "id": 5, "veiculo_id": 20, "veiculo_nome": "Veiculo Flex",
                "placa": "FLEX-2020", "km": 500, "quantidade_litros": 50,
                "status": "abastecido", "combustivel_tipo": "gasolina",
                "data_evento": datetime.datetime(2026, 9, 15, 8, 0),
            },
        ]

        payload = server._montar_frota_consumo_rodagem(
            rows,
            data_inicio="2026-09-01",
            data_fim="2026-09-30",
            veiculos=[{"id": 10, "nome": "Caminhao 10", "placa": "ABC-1010"}],
        )

        self.assertEqual(1100, payload["resumo"]["km_total_rodado"])
        self.assertEqual(240.0, payload["resumo"]["litros_totais_usados"])
        self.assertEqual(0.0, payload["resumo"]["litros_diesel_s500"])
        self.assertEqual(220.0, payload["resumo"]["litros_diesel_s10"])
        self.assertEqual(20.0, payload["resumo"]["litros_arla"])
        self.assertEqual(220.0, payload["resumo"]["litros_com_rodagem"])
        self.assertEqual(5.0, payload["resumo"]["media_geral_km_l"])
        self.assertEqual(1, payload["resumo"]["veiculos"])
        self.assertEqual([10], [item["veiculo_id"] for item in payload["itens"]])

    def test_consumo_rodagem_rejeita_periodo_invertido(self):
        with self.assertRaisesRegex(ValueError, "data inicial"):
            server._montar_frota_consumo_rodagem(
                [], data_inicio="2026-10-02", data_fim="2026-10-01"
            )

    def test_interface_e_documentacao_expoem_relatorio(self):
        page = (SOURCE_DIR / "RioBranco.html").read_text(encoding="utf-8")
        script = (SOURCE_DIR / "script.js").read_text(encoding="utf-8")
        api_docs = (SOURCE_DIR / "docs/API_E_DADOS.md").read_text(encoding="utf-8")

        self.assertIn('id="frotaRelMensalMes"', page)
        self.assertIn('id="frotaRelMensalAbastecimentosBody"', page)
        self.assertIn('id="frotaConsumoDataInicio"', page)
        self.assertIn('id="frotaConsumoBody"', page)
        self.assertIn("Diesel S500", page)
        self.assertIn("/api/frota_relatorio/mensal", script)
        self.assertIn("/api/frota_relatorio/consumo-rodagem", script)
        self.assertIn("litros_diesel_s500", script)
        self.assertIn("litros_arla", script)
        self.assertIn("imprimirRelatorioMensalFrota", script)
        self.assertIn("imprimirRelatorioConsumoRodagem", script)
        self.assertIn("GET /api/frota_relatorio/mensal", api_docs)
        self.assertIn("GET /api/frota_relatorio/consumo-rodagem", api_docs)


if __name__ == "__main__":
    unittest.main()
