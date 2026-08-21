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


class _RecordingCursor(_Cursor):
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class _RecordingConnection(_Connection):
    def __init__(self):
        super().__init__()
        self.recording_cursor = _RecordingCursor()

    def cursor(self, dictionary=False):
        return self.recording_cursor


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
            mock.patch.object(
                server,
                "_estoque_xml_destinos_manutencao",
                return_value={},
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

    def test_preparacao_rejeita_nota_fora_do_filtro_de_movimento(self):
        connection = _Connection()
        nota = {"canonicos": [{"numero_nota": "123"}]}

        with (
            mock.patch.object(server, "get_conn", return_value=connection),
            mock.patch.object(
                server,
                "_estoque_xml_carregar_notas",
                return_value={"nota-entrada": nota},
            ),
            mock.patch.object(
                server,
                "_estoque_xml_referencias_lancadas",
                return_value=set(),
            ),
            mock.patch.object(
                server,
                "_estoque_xml_destinos_manutencao",
                return_value={},
            ),
            mock.patch.object(
                server,
                "_estoque_xml_nota_publica",
                return_value={
                    "numero_nota": "123",
                    "tipo_movimento": "entrada",
                    "status": "pendente",
                },
            ),
            mock.patch.object(server, "_estoque_xml_preview") as preview,
            server.app.test_client() as client,
        ):
            response = client.post(
                "/api/estoque/importacoes-xml/lote/preparar",
                json={"chaves": ["nota-entrada"], "tipo_movimento": "saida"},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual([], payload["previews"])
        self.assertEqual(1, payload["meta"]["com_erro"])
        self.assertIn("fora do filtro", payload["erros"][0]["erro"])
        preview.assert_not_called()

    def test_interface_divide_selecao_e_exibe_progresso(self):
        with open("script.js", "r", encoding="utf-8") as source:
            script = source.read()
        with open("RioBranco.html", "r", encoding="utf-8") as source:
            page = source.read()

        self.assertIn("_dividirImportacoesXmlEmLotes(chaves, tamanhoLote)", script)
        self.assertIn("lote ${loteIndex + 1} de ${totalLotes}", script)
        self.assertIn('id="estoqueXmlLoteProgresso"', page)

    def test_interface_limita_acoes_as_notas_visiveis_no_filtro(self):
        with open("script.js", "r", encoding="utf-8") as source:
            script = source.read()

        self.assertIn("function _chavesImportacoesXmlSelecionadasVisiveis()", script)
        self.assertGreaterEqual(
            script.count("const chaves = _chavesImportacoesXmlSelecionadasVisiveis();"),
            2,
        )
        self.assertIn("chavesVisiveis.has(String(chave))", script)
        self.assertIn("tipo_movimento: tipoMovimentoFiltro || null", script)

    def test_interface_remove_notas_ja_consolidadas_sem_exigir_revisao(self):
        with open("script.js", "r", encoding="utf-8") as source:
            script = source.read()

        self.assertIn('=== "nota ja consolidada no estoque"', script)
        self.assertIn("chavesConsolidadas.has(String(row?.nota_key || \"\"))", script)
        self.assertIn("notasJaConsolidadas.length ? \"concluido\" : \"pendente\"", script)

    def test_descarte_pendente_preserva_origem_e_bloqueia_fila(self):
        connection = _RecordingConnection()
        nota = {
            "canonicos": [
                {"id": 10, "chave_nfe": "1" * 44, "numero_nota": "123"}
            ]
        }

        with (
            mock.patch.object(server, "get_conn", return_value=connection),
            mock.patch.object(
                server,
                "_estoque_xml_carregar_notas",
                return_value={"1" * 44: nota},
            ),
            mock.patch.object(
                server,
                "_estoque_xml_referencias_lancadas",
                return_value=set(),
            ),
            mock.patch.object(
                server,
                "_estoque_xml_destinos_manutencao",
                return_value={},
            ),
            server.app.test_client() as client,
        ):
            response = client.post(
                "/api/estoque/importacoes-xml/descartar",
                json={"chaves": ["1" * 44]},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.get_json()["meta"]["descartadas"])
        self.assertTrue(connection.committed)
        sql = "\n".join(item[0] for item in connection.recording_cursor.statements)
        self.assertIn("INSERT INTO estoque_xml_descartes", sql)
        self.assertIn("UPDATE estoque_xml_frete_pre_vinculos", sql)
        self.assertNotIn("DELETE FROM importar_xml_estoque_itens", sql)

    def test_descarte_bloqueia_nota_que_ja_movimentou_estoque(self):
        connection = _RecordingConnection()
        nota = {
            "canonicos": [
                {"id": 10, "chave_nfe": "2" * 44, "numero_nota": "456"}
            ]
        }

        with (
            mock.patch.object(server, "get_conn", return_value=connection),
            mock.patch.object(
                server,
                "_estoque_xml_carregar_notas",
                return_value={"2" * 44: nota},
            ),
            mock.patch.object(
                server,
                "_estoque_xml_referencias_lancadas",
                return_value={10},
            ),
            mock.patch.object(
                server,
                "_estoque_xml_destinos_manutencao",
                return_value={},
            ),
            server.app.test_client() as client,
        ):
            response = client.post(
                "/api/estoque/importacoes-xml/descartar",
                json={"chaves": ["2" * 44]},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual(0, payload["meta"]["descartadas"])
        self.assertIn("ja comecou", payload["erros"][0]["erro"])
        sql = "\n".join(item[0] for item in connection.recording_cursor.statements)
        self.assertNotIn("INSERT INTO estoque_xml_descartes", sql)

    def test_interface_oferece_exclusao_individual_e_em_massa(self):
        with open("script.js", "r", encoding="utf-8") as source:
            script = source.read()
        with open("RioBranco.html", "r", encoding="utf-8") as source:
            page = source.read()

        self.assertIn("function excluirImportacaoXmlEstoque", script)
        self.assertIn("function excluirSelecionadasXmlEstoque", script)
        self.assertIn("/api/estoque/importacoes-xml/descartar", script)
        self.assertIn('id="estoqueXmlExcluirLoteBtn"', page)
        self.assertIn('id="estoqueXmlPendentesLote"', page)
        self.assertIn("lote_importacao", script)

    def test_resumo_identifica_o_zip_como_lote_de_importacao(self):
        row = {
            "id": 10,
            "arquivo_origem": "XMLs-05-08-2026_06-55-43.zipNFe123.xml",
            "tipo_movimento": "ENTRADA_ESTOQUE",
            "numero_nota": "123",
        }
        resumo = server._estoque_xml_nota_publica(
            {"nota_key": "nota-123", "canonicos": [row], "arquivo_ids": {1}},
            set(),
        )

        self.assertEqual("XMLs-05-08-2026_06-55-43.zip", resumo["lote_importacao"])

    def test_preparacao_isola_falha_de_uma_nota_e_mantem_as_demais(self):
        connection = _RecordingConnection()
        notas = {
            "nota-com-erro": {"canonicos": [{"id": 1, "numero_nota": "100"}]},
            "nota-valida": {"canonicos": [{"id": 2, "numero_nota": "200"}]},
        }

        with (
            mock.patch.object(server, "get_conn", return_value=connection),
            mock.patch.object(server, "_estoque_xml_carregar_notas", return_value=notas),
            mock.patch.object(server, "_estoque_xml_referencias_lancadas", return_value=set()),
            mock.patch.object(server, "_estoque_xml_destinos_manutencao", return_value={}),
            mock.patch.object(
                server,
                "_estoque_xml_nota_publica",
                side_effect=[
                    {"numero_nota": "100", "tipo_movimento": "entrada", "status": "pendente"},
                    {"numero_nota": "200", "tipo_movimento": "entrada", "status": "pendente"},
                ],
            ),
            mock.patch.object(
                server,
                "_estoque_xml_preview",
                side_effect=[ValueError("produto precisa de revisao"), {"itens": [{"xml_item_id": 2}] }],
            ),
            server.app.test_client() as client,
        ):
            response = client.post(
                "/api/estoque/importacoes-xml/lote/preparar",
                json={"chaves": ["nota-com-erro", "nota-valida"]},
            )

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, payload["meta"]["preparadas"])
        self.assertEqual(1, payload["meta"]["com_erro"])
        self.assertIn("precisa de revisao", payload["erros"][0]["erro"])
        sql = "\n".join(item[0] for item in connection.recording_cursor.statements)
        self.assertIn("ROLLBACK TO SAVEPOINT estoque_xml_preparo_nota", sql)

    def test_interface_filtra_fila_e_mantem_notas_invalidas_pendentes(self):
        with open("script.js", "r", encoding="utf-8") as source:
            script = source.read()
        with open("RioBranco.html", "r", encoding="utf-8") as source:
            page = source.read()

        self.assertIn('id="estoqueXmlPendentesBusca"', page)
        self.assertIn('id="estoqueXmlPendentesClassificacao"', page)
        self.assertIn("function limparFiltrosImportacoesXmlEstoque", script)
        self.assertIn("serao ignoradas e continuarao pendentes", script)
        self.assertIn("importacoesXmlMeta?.lote_recomendado", script)
        self.assertNotIn("O lote nao foi iniciado porque existem notas", script)

    def test_menu_separa_compras_e_tarefas_de_estoque(self):
        with open("script.js", "r", encoding="utf-8") as source:
            script = source.read()
        with open("RioBranco.html", "r", encoding="utf-8") as source:
            page = source.read()

        self.assertIn('data-tab="compras"', page)
        self.assertIn('data-compras-view="importar_xml_bipe"', page)
        self.assertIn('data-compras-view="importar_xml_auto"', page)
        self.assertIn('id="estoqueImportPreviewLayer"', page)
        self.assertIn("estoque-xml-filter-row", page)
        self.assertIn("estoque-xml-action-row", page)
        self.assertIn('id="submenuEstoque"', page)
        self.assertNotIn('data-monitor-view="importar_xml"', page)
        self.assertIn('id="estoqueMovimentoManualBox"', page)
        self.assertIn("function openComprasView", script)
        self.assertIn('setEstoqueView("importar_xml_auto")', script)
        self.assertIn("function fecharModalImportacaoEstoqueBackdrop", script)
        self.assertIn('["importar_xml_bipe", "importar_xml_auto", "movimentar"].includes(nextView)', script)


if __name__ == "__main__":
    unittest.main()
