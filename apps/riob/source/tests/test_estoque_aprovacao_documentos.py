import unittest
from unittest import mock

import server


class _CursorCarga:
    def __init__(self, row=None):
        self.executions = []
        self.lastrowid = 0
        self.row = row or {
            "id": 7,
            "nome": "Mapa 123",
            "veiculo_numero": "13",
            "mapa_numero": "123",
            "estoque_baixado_em": None,
            "estoque_rejeitado_em": None,
            "estoque_rejeitado_por": "",
            "estoque_rejeitado_motivo": "",
        }

    def execute(self, sql, params=()):
        self.executions.append((sql, params))
        if "INSERT INTO estoque_movimentos" in sql:
            self.lastrowid += 1

    def fetchone(self):
        return self.row


class EstoqueAprovacaoDocumentosTests(unittest.TestCase):
    def test_mudanca_de_status_do_frete_nao_baixa_pdf_automaticamente(self):
        with mock.patch.object(server, "_baixar_estoque_carga") as baixar:
            result = server._sincronizar_baixa_estoque_frete(
                mock.Mock(),
                {"status": "liberado", "carga_id": 7},
                {"status": "carregado", "carga_id": 7},
                usuario="Operador",
            )
        baixar.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual("aguardando_aprovacao_documento", result["motivo"])

    def test_pdf_coberto_por_xml_nao_gera_nova_saida(self):
        cursor = _CursorCarga()
        with mock.patch.object(server, "_xmls_saida_confirmados_carga", return_value=[{
            "numero_nota": "456",
        }]), mock.patch.object(server, "_listar_itens_carga_estoque") as listar_itens:
            result = server._baixar_estoque_carga(cursor, 7, usuario="Operador")
        listar_itens.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual("coberta_por_xml", result["motivo"])
        self.assertEqual(["456"], result["notas_xml"])
        self.assertFalse(any("INSERT INTO estoque_movimentos" in sql for sql, _ in cursor.executions))

    def test_pdf_com_varios_itens_usa_referencia_unica_por_item(self):
        cursor = _CursorCarga()
        itens = [
            {"id": 21, "codigo_produto": "A", "nome_produto": "Produto A", "quantidade_total": 3},
            {"id": 22, "codigo_produto": "B", "nome_produto": "Produto B", "quantidade_total": 5},
        ]
        produto = {
            "id": 10,
            "codigo_barras": "789",
            "codigo_produto_nfe": "A",
            "nome_produto": "Produto",
            "estoque_minimo": 0,
        }
        with mock.patch.object(server, "_xmls_saida_confirmados_carga", return_value=[]), \
             mock.patch.object(server, "_listar_itens_carga_estoque", return_value=itens), \
             mock.patch.object(server, "_buscar_produto_cadastro_por_referencias", return_value=produto), \
             mock.patch.object(server, "_estoque_resumo_produtos_data", return_value={"rows": []}) as resumo, \
             mock.patch.object(server, "_saldo_atual_produto_estoque", return_value=20) as saldo:
            result = server._baixar_estoque_carga(cursor, 7, usuario="Operador")

        inserts = [
            (sql, params)
            for sql, params in cursor.executions
            if "INSERT INTO estoque_movimentos" in sql
        ]
        self.assertTrue(result["ok"])
        self.assertEqual(2, result["itens_baixados"])
        self.assertEqual(2, len(inserts))
        self.assertTrue(all("'carga_pdf_item'" in sql for sql, _ in inserts))
        self.assertEqual([21, 22], [params[8] for _, params in inserts])
        self.assertEqual(2, len({params[8] for _, params in inserts}))
        resumo.assert_called_once_with(incluir_fornecedores=False, somente_saldos=True)
        saldo.assert_called_once()

    def test_pdf_rejeitado_nao_pode_gerar_saida(self):
        cursor = _CursorCarga({
            "id": 7,
            "nome": "Mapa 123",
            "veiculo_numero": "13",
            "mapa_numero": "123",
            "estoque_baixado_em": None,
            "estoque_rejeitado_em": "2026-10-27 09:00:00",
            "estoque_rejeitado_por": "Operador",
            "estoque_rejeitado_motivo": "Anterior ao acerto",
        })
        with mock.patch.object(server, "_xmls_saida_confirmados_carga") as listar_xmls, \
             mock.patch.object(server, "_listar_itens_carga_estoque") as listar_itens:
            result = server._baixar_estoque_carga(cursor, 7, usuario="Operador")
        listar_xmls.assert_not_called()
        listar_itens.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual("carga_rejeitada", result["motivo"])
        self.assertFalse(any("INSERT INTO estoque_movimentos" in sql for sql, _ in cursor.executions))

    def test_rejeicao_e_logica_auditavel_e_nao_movimenta_estoque(self):
        cursor = _CursorCarga()
        with mock.patch.object(server, "_xmls_saida_confirmados_carga", return_value=[]):
            result = server._rejeitar_carga_pdf_estoque(
                cursor,
                7,
                usuario="Operador",
                motivo="Carga anterior ao acerto de estoque",
            )
        self.assertTrue(result["ok"])
        self.assertEqual("Operador", result["rejeitada_por"])
        sqls = [sql for sql, _ in cursor.executions]
        self.assertTrue(any("estoque_rejeitado_em=NOW()" in sql for sql in sqls))
        self.assertFalse(any("DELETE FROM cargas" in sql for sql in sqls))
        self.assertFalse(any("INSERT INTO estoque_movimentos" in sql for sql in sqls))

    def test_rejeicao_exige_sessao_e_recurso(self):
        client = server.app.test_client()
        sem_sessao = client.post(
            "/api/estoque/aprovacoes-pdf/7/rejeitar",
            json={"motivo": "Carga antiga"},
        )
        self.assertEqual(401, sem_sessao.status_code)
        sem_recurso = client.post(
            "/api/estoque/aprovacoes-pdf/7/rejeitar",
            json={"motivo": "Carga antiga"},
            headers={"X-Usuario-Id": "9", "X-Usuario-Perfil": "usuario"},
        )
        self.assertEqual(403, sem_recurso.status_code)

    def test_rejeicao_autorizada_usa_mesmo_recurso_da_tela(self):
        conn = mock.Mock()
        conn.cursor.return_value = mock.Mock()
        with mock.patch.object(server, "get_conn", return_value=conn), \
             mock.patch.object(server, "_usuario_ator_req", return_value="Operador"), \
             mock.patch.object(server, "_rejeitar_carga_pdf_estoque", return_value={
                 "ok": True,
                 "carga_id": 7,
             }) as rejeitar:
            response = server.app.test_client().post(
                "/api/estoque/aprovacoes-pdf/7/rejeitar",
                json={"motivo": "Carga antiga"},
                headers={
                    "X-Usuario-Id": "9",
                    "X-Usuario-Perfil": "usuario",
                    "X-Usuario-Recursos": "estoque_documentos_aprovar",
                },
            )
        self.assertEqual(200, response.status_code)
        rejeitar.assert_called_once_with(
            conn.cursor.return_value,
            7,
            usuario="Operador",
            motivo="Carga antiga",
        )
        conn.commit.assert_called_once_with()

    def test_status_publico_distingue_pendente_xml_baixado_e_rejeitado(self):
        base = {
            "id": 7,
            "arquivo_origem": "carga.pdf",
            "itens_total": 2,
            "quantidade_itens": 18,
            "xml_total": 0,
            "notas_xml": "",
        }
        self.assertEqual("pendente", server._carga_pdf_aprovacao_publica(base)["status"])
        self.assertEqual(
            "coberto_xml",
            server._carga_pdf_aprovacao_publica({**base, "xml_total": 1, "notas_xml": "9"})["status"],
        )
        self.assertEqual(
            "baixado",
            server._carga_pdf_aprovacao_publica({**base, "estoque_baixado_em": "2026-10-22 10:00:00"})["status"],
        )
        rejeitado = server._carga_pdf_aprovacao_publica({
            **base,
            "estoque_rejeitado_em": "2026-10-27 09:00:00",
            "estoque_rejeitado_por": "Operador",
            "estoque_rejeitado_motivo": "Anterior ao acerto",
        })
        self.assertEqual("rejeitado", rejeitado["status"])
        self.assertEqual("Anterior ao acerto", rejeitado["estoque_rejeitado_motivo"])


if __name__ == "__main__":
    unittest.main()
