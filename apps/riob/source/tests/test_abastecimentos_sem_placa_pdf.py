import datetime
import unittest
from pathlib import Path
from unittest import mock

import server


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
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


class AbastecimentosSemPlacaPdfTests(unittest.TestCase):
    def test_relatorio_filtra_apenas_veiculos_sem_placa_identificada(self):
        rows = [
            {
                "id": 293,
                "veiculo_id": 59,
                "km": 0,
                "posto": "Auto Posto Reunidos Ltda",
                "combustivel_tipo": "diesel_s10",
                "chave_acesso_nfe": "1" * 44,
                "numero_nota": "72477",
                "emitente_nome": "",
                "quantidade_litros": 53.04,
                "valor": 363.32,
                "status": "abastecido",
                "veiculo_nome": "SemPlacaS10",
                "placa": "SEM-SS10",
                "modelo": "",
                "data_evento": datetime.datetime(2026, 6, 20, 9, 0),
            },
            {
                "id": 294,
                "veiculo_id": 60,
                "km": 0,
                "posto": "Paulo Sergio da Silva Combustiveis Ltda",
                "combustivel_tipo": "gasolina",
                "chave_acesso_nfe": "2" * 44,
                "numero_nota": "72473",
                "emitente_nome": "",
                "quantidade_litros": 28.28,
                "valor": 185.23,
                "status": "abastecido",
                "veiculo_nome": "SemPlacaFlex",
                "placa": "SEM-Flex",
                "modelo": "",
                "data_evento": datetime.datetime(2026, 6, 20, 10, 0),
            },
            {
                "id": 12,
                "veiculo_id": 5,
                "km": 120000,
                "posto": "Auto Posto Reunidos Ltda",
                "combustivel_tipo": "diesel_500",
                "chave_acesso_nfe": "",
                "numero_nota": "",
                "emitente_nome": "",
                "quantidade_litros": 80,
                "valor": 500,
                "status": "abastecido",
                "veiculo_nome": "Veiculo normal",
                "placa": "SEM-1234",
                "modelo": "",
                "data_evento": datetime.datetime(2026, 6, 20, 11, 0),
            },
        ]
        cursor = _Cursor(rows)
        connection = _Connection(cursor)

        with (
            mock.patch.object(server, "get_conn", return_value=connection),
            mock.patch.object(server, "_limpar_fretes_finalizados_expirados"),
            mock.patch.object(
                server,
                "_build_abastecimentos_report_pdf",
                wraps=server._build_abastecimentos_report_pdf,
            ) as build_pdf,
            server.app.test_client() as client,
        ):
            response = client.get(
                "/api/frota_relatorio"
                "?tipo=abastecimentos_sem_placa"
                "&data_inicio=2026-06-01"
                "&data_fim=2026-06-30"
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/pdf", response.mimetype)
        self.assertIn(
            "abastecimentos_sem_placa.pdf",
            response.headers.get("Content-Disposition", ""),
        )
        self.assertTrue(response.data.startswith(b"%PDF"))
        self.assertEqual(2, len(build_pdf.call_args.args[0]))
        self.assertEqual(
            "Relatório de Abastecimentos sem Placa Identificada",
            build_pdf.call_args.kwargs["titulo"],
        )
        self.assertEqual(
            (
                datetime.date(2026, 6, 1),
                datetime.date(2026, 6, 30),
            ),
            cursor.executed[0][1],
        )
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)
        response.close()

    def test_interface_expoe_relatorio_sem_placa(self):
        page = Path("RioBranco.html").read_text(encoding="utf-8")
        script = Path("script.js").read_text(encoding="utf-8")

        self.assertIn("Abastecimentos sem Placa Identificada", page)
        self.assertIn(
            "gerarRelatorioFrota('abastecimentos_sem_placa')",
            page,
        )
        self.assertIn('"abastecimentos_sem_placa"', script)


if __name__ == "__main__":
    unittest.main()
