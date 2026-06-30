import datetime
import os
import unittest
from pathlib import Path
from unittest import mock

import server


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.closed = False

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def fetchall(self):
        return list(self.rows)

    def close(self):
        self.closed = True


class _Connection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.closed = False

    def cursor(self, dictionary=False):
        return self.cursor_instance

    def close(self):
        self.closed = True


class AbastecimentosCriticosPdfTests(unittest.TestCase):
    def test_relatorio_gera_pdf_com_tres_secoes_agrupadas_por_posto(self):
        rows = [
            {
                "id": 1,
                "chave_nfe": "1" * 44,
                "placa_xml": "AIO267S",
                "vinculacao_origem": "placa_similar",
                "motivo": "Placa semelhante.",
                "atualizado_em": datetime.datetime(2026, 6, 18, 9, 0),
                "posto_nome": "AUTO POSTO TESTE",
                "data_emissao": "2026-06-18T08:30:15-03:00",
                "km_final": 447183,
                "valor_produto": 250.5,
                "valor_total": 250.5,
                "veiculo_nome": "23",
                "veiculo_placa": "AIO-2675",
                "veiculo_km_atual": 447000,
            },
            {
                "id": 2,
                "chave_nfe": "2" * 44,
                "placa_xml": "",
                "vinculacao_origem": "automatico",
                "motivo": "XML sem placa; vinculo automatico nao realizado.",
                "atualizado_em": datetime.datetime(2026, 6, 18, 10, 0),
                "posto_nome": "POSTO CENTRAL",
                "data_emissao": "2026-06-18T09:45:00-03:00",
                "km_final": 0,
                "valor_produto": 0,
                "valor_total": 199.9,
                "veiculo_nome": "",
                "veiculo_placa": "",
                "veiculo_km_atual": 0,
            },
            {
                "id": 3,
                "chave_nfe": "3" * 44,
                "placa_xml": "AKL5B81",
                "vinculacao_origem": "automatico",
                "motivo": "KM do XML incompativel com o historico do veiculo.",
                "atualizado_em": datetime.datetime(2026, 6, 18, 11, 0),
                "posto_nome": "POSTO CENTRAL",
                "data_emissao": "2026-06-18T10:15:00-03:00",
                "km_final": 1,
                "valor_produto": 255.6,
                "valor_total": 255.6,
                "veiculo_nome": "51",
                "veiculo_placa": "AKL-5B81",
                "veiculo_km_atual": 184331,
            },
        ]
        cursor = _Cursor(rows)
        connection = _Connection(cursor)

        with (
            mock.patch.object(server, "get_conn", return_value=connection),
            mock.patch.object(
                server,
                "_limpar_fretes_finalizados_expirados",
            ),
            server.app.test_client() as client,
        ):
            response = client.get(
                "/api/frota_relatorio"
                "?tipo=abastecimentos_criticos"
                "&data_inicio=2026-06-01"
                "&data_fim=2026-06-30"
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/pdf", response.mimetype)
        self.assertIn(
            "abastecimentos_criticos.pdf",
            response.headers.get("Content-Disposition", ""),
        )
        self.assertTrue(response.data.startswith(b"%PDF"))
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)
        self.assertEqual(
            (
                datetime.date(2026, 6, 1),
                datetime.date(2026, 6, 30),
            ),
            cursor.executed[0][1],
        )
        response.close()

    def test_pdf_usa_logo_cabecalho_rodape_e_folhas_separadas(self):
        categorias = {
            "placas_similares": [
                {
                    "posto": "AUTO POSTO TESTE",
                    "placa_xml": "AIO267S",
                    "veiculo_placa": "AIO-2675",
                    "veiculo_nome": "23",
                    "data_hora": "18/06/2026 08:30:15",
                }
            ],
            "sem_placa": [
                {
                    "posto": "POSTO CENTRAL",
                    "chave_xml": "2" * 44,
                    "valor": 199.9,
                    "data_hora": "18/06/2026 09:45:00",
                }
            ],
            "km_incompativel": [
                {
                    "posto": "POSTO CENTRAL",
                    "placa_xml": "AKL5B81",
                    "veiculo_nome": "51",
                    "km_final": 1,
                    "veiculo_km_atual": 184331,
                    "chave_xml": "3" * 44,
                    "valor": 255.6,
                    "data_hora": "18/06/2026 10:15:00",
                }
            ],
        }
        arquivo = server._build_abastecimentos_criticos_pdf(
            categorias,
            {"resumo": ["Período: teste"]},
        )
        try:
            conteudo = Path(arquivo).read_bytes()
            self.assertTrue(conteudo.startswith(b"%PDF"))
            self.assertGreaterEqual(conteudo.count(b"/Type /Page"), 3)
            self.assertTrue(Path("logo.png").is_file())
        finally:
            if os.path.exists(arquivo):
                os.unlink(arquivo)

    def test_interface_expoe_relatorio_critico_em_pdf(self):
        page = Path("RioBranco.html").read_text(encoding="utf-8")
        script = Path("script.js").read_text(encoding="utf-8")

        self.assertIn(">Criticas de Abastecimento</span>", page)
        self.assertNotIn("Criticas de Abastecimento (Excel)", page)
        self.assertIn(
            "gerarRelatorioFrota('abastecimentos_criticos')",
            page,
        )
        self.assertIn('"abastecimentos_criticos"', script)


if __name__ == "__main__":
    unittest.main()
