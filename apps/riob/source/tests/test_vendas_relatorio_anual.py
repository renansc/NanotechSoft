import datetime as dt
import unittest
from pathlib import Path
from unittest import mock

import server


class VendasRelatorioAnualTest(unittest.TestCase):
    @staticmethod
    def _row(data_ref, litros, vendedor="VENDEDOR 1", cliente="CLIENTE A"):
        return {
            "data_ref": data_ref,
            "litros": litros,
            "tab_venda": 1,
            "vendedor_key_upper": vendedor,
            "vendedor_key": vendedor,
            "vendedor_nome": vendedor,
            "cliente_norm": cliente,
            "chave": cliente,
            "cliente": cliente,
        }

    def test_comparativo_anual_calcula_volume_percentual_e_movimento(self):
        rows = [
            self._row(dt.date(2025, 1, 10), 100),
            self._row(dt.date(2026, 1, 10), 120),
            self._row(dt.date(2026, 2, 10), 50),
        ]

        payload = server._vendas_comparativo_anual(
            rows,
            referencia=dt.date(2026, 9, 8),
        )

        self.assertEqual(2026, payload["ano_atual"])
        self.assertEqual(2025, payload["ano_anterior"])
        self.assertEqual(9, len(payload["meses"]))
        self.assertEqual(1.2, payload["comparativo_mensal"][0]["volume_atual"])
        self.assertEqual(1.0, payload["comparativo_mensal"][0]["volume_anterior"])
        self.assertEqual(0.2, payload["comparativo_mensal"][0]["diferenca_volume"])
        self.assertEqual(20.0, payload["comparativo_mensal"][0]["variacao_percentual"])
        self.assertEqual("acrescimo", payload["comparativo_mensal"][0]["movimento"])
        self.assertEqual("sem_base", payload["comparativo_mensal"][1]["movimento"])
        self.assertIsNone(payload["comparativo_mensal"][1]["variacao_percentual"])
        self.assertEqual(0.7, payload["resumo"]["diferenca_volume"])
        self.assertEqual(70.0, payload["resumo"]["variacao_percentual"])

    def test_filtros_de_vendedor_e_cliente_sao_combinados(self):
        rows = [
            self._row(dt.date(2026, 1, 10), 100, "VENDEDOR 1", "CLIENTE A"),
            self._row(dt.date(2026, 1, 10), 200, "VENDEDOR 1", "CLIENTE B"),
            self._row(dt.date(2026, 1, 10), 300, "VENDEDOR 2", "CLIENTE A"),
        ]

        filtradas = server._vendas_rows_filtradas_base(rows, "VENDEDOR 1", "CLIENTE A")

        self.assertEqual(1, len(filtradas))
        self.assertEqual(100, filtradas[0]["litros"])

    def test_comparativo_ignora_meses_futuros_do_ano_em_andamento(self):
        rows = [
            self._row(dt.date(2025, 12, 10), 500),
            self._row(dt.date(2026, 9, 8), 100),
        ]

        payload = server._vendas_comparativo_anual(
            rows,
            referencia=dt.date(2026, 9, 8),
        )

        self.assertEqual("Set", payload["meses"][-1]["label"])
        self.assertNotIn("Dez", [item["label"] for item in payload["meses"]])

    def test_payload_anual_publica_filtros_e_opcoes(self):
        rows = [
            self._row(dt.date(2025, 1, 10), 100, "VENDEDOR 1", "CLIENTE A"),
            self._row(dt.date(2026, 1, 10), 120, "VENDEDOR 1", "CLIENTE A"),
            self._row(dt.date(2026, 9, 8), 300, "VENDEDOR 2", "CLIENTE B"),
        ]
        cache = {"id": "cache-1", "source_path": "/dados/vendas.xlsx", "source_size": 123}
        source = {"name": "vendas.xlsx", "size": 123, "mtime": "2026-09-08 08:00:00"}
        cfg = {"source_type": "csv_relatorios_dir"}

        with mock.patch.object(server, "_vendas_obter_cache_ativo", return_value=(cache, source, cfg)), \
                mock.patch.object(server, "_vendas_relatorio_base_rows", return_value=(rows, cache)):
            payload = server._coletar_relatorio_vendas_percentual_vendas_anual(
                filtro_vendedor="VENDEDOR 1",
                filtro_cliente="CLIENTE A",
            )

        self.assertEqual("vendas.xlsx", payload["arquivo"]["nome"])
        self.assertEqual("VENDEDOR 1", payload["filtros"]["vendedor"])
        self.assertEqual("CLIENTE A", payload["filtros"]["cliente"])
        self.assertEqual(2, len(payload["vendedores"]))
        self.assertEqual(2, len(payload["clientes_disponiveis"]))
        self.assertEqual(1.2, payload["resumo_geral"]["total_atual"])
        self.assertEqual(1.0, payload["resumo_geral"]["total_anterior"])

    def test_telas_expoem_cliente_e_dashboard_anual(self):
        root = Path(server.__file__).resolve().parent
        html = (root / "RioBranco.html").read_text(encoding="utf-8")
        script = (root / "script.js").read_text(encoding="utf-8")

        self.assertIn('id="vendasDiarioCliente"', html)
        self.assertIn('id="vendasRelCliente"', html)
        self.assertIn('data-dashboard-view="vendas_anual"', html)
        self.assertIn('id="vendasViewRelatorioAnual"', html)
        self.assertIn("function carregarDashboardVendasAnual", script)
        self.assertIn("function carregarRelatorioVendasAnual", script)


if __name__ == "__main__":
    unittest.main()
