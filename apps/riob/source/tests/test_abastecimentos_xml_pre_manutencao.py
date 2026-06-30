import json
import unittest
from pathlib import Path
from unittest import mock

import server
from ImportarXml.importador_xml_homologacao import (
    extrair_abastecimento,
    parse_nfe,
)


class _Cursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []
        self.lastrowid = 321

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        return None


class _Connection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self, dictionary=False):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        return None


class AbastecimentosXmlPreManutencaoTests(unittest.TestCase):
    def test_nota_real_de_filtro_vai_para_pre_manutencao(self):
        arquivo = Path(
            "ImportarXml/uploads_xml_homologacao/"
            "8f69351aa7564e2bb50d03223fc2e750_"
            "23_NF-e-41260630365872000114550100000981781008425839.xml"
        )
        cabecalho, itens = parse_nfe(arquivo)
        row = extrair_abastecimento(cabecalho, itens)
        row["dados_json"] = json.dumps(
            {"cab": cabecalho, "itens": itens},
            ensure_ascii=False,
        )

        classificacao = server._abastecimento_xml_classificar_nota(
            row,
            "diesel_500",
        )
        itens_manutencao = server._abastecimento_xml_itens(row)

        self.assertEqual("manutencao", classificacao["destino"])
        self.assertEqual("FILTRO - H 1271", itens_manutencao[0]["nome_produto"])
        self.assertEqual(1.0, itens_manutencao[0]["quantidade"])
        self.assertEqual(60.0, itens_manutencao[0]["valor_total"])

    def test_gasolina_e_classificada_como_abastecimento(self):
        row = {
            "combustivel": "GASOLINA C COMUM",
            "litros": 27.661,
            "valor_unitario": 6.69,
            "valor_produto": 185.05,
            "dados_json": json.dumps(
                {
                    "itens": [
                        {
                            "nItem": "1",
                            "descricao_produto": "GASOLINA COMUM",
                            "quantidade": 27.661,
                            "valor_unitario": 6.69,
                            "valor_total_item": 185.05,
                        }
                    ]
                }
            ),
        }

        classificacao = server._abastecimento_xml_classificar_nota(
            row,
            "diesel_500",
        )

        self.assertEqual("abastecimento", classificacao["destino"])
        self.assertEqual("gasolina", classificacao["combustivel_tipo"])

    def test_placa_sem_hifen_e_erro_visual_gera_apenas_sugestao(self):
        veiculos = [
            {"id": 16, "nome": "23", "placa": "AIO-2675"},
            {"id": 20, "nome": "14", "placa": "AIQ-6237"},
        ]

        self.assertEqual(
            "AIO2675",
            server._abastecimento_xml_placa_normalizada("AIO-2675"),
        )
        sugestao = server._abastecimento_xml_veiculo_similar(
            "AIO267S",
            veiculos,
        )

        self.assertIsNotNone(sugestao)
        self.assertEqual(16, sugestao["veiculo"]["id"])
        self.assertGreaterEqual(sugestao["score"], 0.90)

    def test_xml_sem_placa_encontra_coringa_unico_por_combustivel(self):
        veiculos = [
            {
                "id": 58,
                "nome": "SemPlacaS500",
                "placa": "SEM-s500",
                "combustivel_padrao": "diesel_500",
            },
            {
                "id": 59,
                "nome": "SemPlacaS10",
                "placa": "SEM-SS10",
                "combustivel_padrao": "diesel_s10",
            },
            {
                "id": 60,
                "nome": "SemPlacaFlex",
                "placa": "SEM-Flex",
                "combustivel_padrao": "flex",
            },
        ]

        casos = {
            "diesel_500": 58,
            "diesel_s10": 59,
            "arla": 59,
            "gasolina": 60,
            "etanol": 60,
        }
        for combustivel, veiculo_id in casos.items():
            with self.subTest(combustivel=combustivel):
                resultado = server._abastecimento_xml_veiculo_sem_placa(
                    combustivel,
                    veiculos,
                )
                self.assertEqual(1, resultado["candidatos_total"])
                self.assertEqual(veiculo_id, resultado["veiculo"]["id"])

    def test_xml_sem_placa_ambiguo_permanece_sem_vinculo(self):
        veiculos = [
            {
                "id": 60,
                "nome": "SemPlacaFlex",
                "placa": "SEM-Flex",
                "combustivel_padrao": "flex",
            },
            {
                "id": 61,
                "nome": "SemPlacaFlexReserva",
                "placa": "",
                "combustivel_padrao": "flex",
            },
        ]

        resultado = server._abastecimento_xml_veiculo_sem_placa(
            "gasolina",
            veiculos,
        )

        self.assertEqual(2, resultado["candidatos_total"])
        self.assertIsNone(resultado["veiculo"])

    def test_placa_brasileira_valida_nao_e_tratada_como_sem_placa(self):
        veiculo = {
            "id": 62,
            "nome": "Veiculo 62",
            "placa": "SEM-1234",
            "combustivel_padrao": "flex",
        }

        self.assertFalse(server._veiculo_cadastro_sem_placa(veiculo))

    def test_interface_expoe_fila_de_conferencia_de_manutencao(self):
        page = Path("RioBranco.html").read_text(encoding="utf-8")
        script = Path("script.js").read_text(encoding="utf-8")

        self.assertIn('id="manutXmlPendenciasBody"', page)
        self.assertIn("conferirPreLancamentoManutencaoXml", script)
        self.assertIn("pre_lancamento_id", script)

    def test_confirmacao_cria_manutencao_e_finaliza_pre_lancamento(self):
        cursor = _Cursor(
            [
                {
                    "id": 7,
                    "nota_key": "nota-98178",
                    "status": "pendente",
                    "veiculo_id": 16,
                    "numero_nota": "98178",
                    "emitente_nome": "AUTO POSTO REUNIDOS LTDA",
                    "data_documento": "2026-06-01",
                    "km": 447183,
                    "valor": 60,
                    "itens_json": json.dumps(
                        [
                            {
                                "nome_produto": "FILTRO - H 1271",
                                "quantidade": 1,
                                "valor_total": 60,
                            }
                        ]
                    ),
                }
            ]
        )
        connection = _Connection(cursor)

        with (
            mock.patch.object(server, "get_conn", return_value=connection),
            server.app.test_client() as client,
        ):
            response = client.post(
                "/api/manutencoes",
                json={
                    "pre_lancamento_id": 7,
                    "veiculo_id": 16,
                    "tipo": "Troca de filtro",
                    "km": 447183,
                    "valor": 60,
                    "itens_json": [
                        {
                            "nome_produto": "FILTRO - H 1271",
                            "quantidade": 1,
                            "valor_total": 60,
                        }
                    ],
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertTrue(connection.committed)
        sql_executado = "\n".join(sql for sql, _ in cursor.executed)
        self.assertIn("INSERT INTO manutencoes", sql_executado)
        self.assertIn("status='confirmado'", sql_executado)
        self.assertIn("status='manutencao_confirmada'", sql_executado)


if __name__ == "__main__":
    unittest.main()
