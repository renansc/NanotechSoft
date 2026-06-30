import unittest
from unittest import mock

import server


class _Cursor:
    def close(self):
        return None


class _Connection:
    def __init__(self):
        self.committed = False

    def cursor(self, dictionary=False):
        return _Cursor()

    def commit(self):
        self.committed = True

    def rollback(self):
        return None

    def close(self):
        return None


class EstoqueXmlLotesTests(unittest.TestCase):
    def test_preparacao_rejeita_apenas_chamada_acima_do_lote_tecnico(self):
        chaves = [f"nota-{idx}" for idx in range(501)]

        with server.app.test_client() as client:
            response = client.post(
                "/api/estoque/importacoes-xml/lote/preparar",
                json={"chaves": chaves},
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual(500, response.get_json()["lote_maximo"])

    def test_preparacao_aceita_lote_com_500_notas(self):
        connection = _Connection()
        chaves = [f"nota-{idx}" for idx in range(500)]

        with (
            mock.patch.object(server, "get_conn", return_value=connection),
            mock.patch.object(server, "_estoque_xml_carregar_notas", return_value={}),
            mock.patch.object(
                server,
                "_estoque_xml_referencias_lancadas",
                return_value=set(),
            ),
            server.app.test_client() as client,
        ):
            response = client.post(
                "/api/estoque/importacoes-xml/lote/preparar",
                json={"chaves": chaves},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual(500, payload["meta"]["selecionadas"])
        self.assertEqual(500, payload["meta"]["com_erro"])
        self.assertTrue(connection.committed)

    def test_interface_divide_selecao_e_exibe_progresso(self):
        with open("script.js", "r", encoding="utf-8") as source:
            script = source.read()
        with open("RioBranco.html", "r", encoding="utf-8") as source:
            page = source.read()

        self.assertIn("_dividirImportacoesXmlEmLotes(chaves, tamanhoLote)", script)
        self.assertIn("lote ${loteIndex + 1} de ${totalLotes}", script)
        self.assertIn('id="estoqueXmlLoteProgresso"', page)


if __name__ == "__main__":
    unittest.main()
