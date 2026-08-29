import unittest
from unittest import mock
from pathlib import Path

import server


class VendasOrcamentoTests(unittest.TestCase):
    def setUp(self):
        self.parametros = {
            "percentual_bonificacao": 15,
            "percentual_terco": 33,
            "preco_bonificacao": 46.60,
            "preco_seco_retornavel": 44,
            "preco_seco_pet": 30,
        }

    def test_reproduz_exemplo_da_planilha(self):
        calculo = server._calcular_orcamento_vendas(
            [
                {
                    "produto_id": 1,
                    "produto_nome": "Retornável",
                    "categoria": "RETORNAVEL",
                    "unidade": "CX",
                    "quantidade": 210,
                    "preco_unitario": 46.60,
                    "ordem": 1,
                },
                {
                    "produto_id": 2,
                    "produto_nome": "PET 2L",
                    "categoria": "PET_2L",
                    "unidade": "PCT",
                    "quantidade": 960,
                    "preco_unitario": 32.45,
                    "ordem": 2,
                },
            ],
            self.parametros,
        )

        self.assertEqual(210.0, calculo["quantidade_retornavel"])
        self.assertEqual(960.0, calculo["quantidade_pet"])
        self.assertEqual(1170.0, calculo["quantidade_total"])
        self.assertEqual(144.0, calculo["quantidade_bonificacao"])
        self.assertEqual(40938.0, calculo["valor_bruto"])
        self.assertEqual(6710.40, calculo["valor_bonificacao"])
        self.assertEqual(2214.43, calculo["valor_terco"])
        self.assertEqual(34227.60, calculo["valor_liquido"])
        self.assertEqual(36442.03, calculo["valor_real"])
        self.assertEqual(38040.0, calculo["valor_seco"])
        self.assertEqual(1597.97, calculo["diferenca_total_real"])
        self.assertEqual(4.2008, calculo["percentual_total_real"])

    def test_nao_aceita_item_usado_sem_preco(self):
        with self.assertRaisesRegex(ValueError, "configure o preço"):
            server._calcular_orcamento_vendas(
                [{
                    "produto_nome": "PET 600ML",
                    "categoria": "PET_600ML",
                    "quantidade": 1,
                    "preco_unitario": 0,
                }],
                self.parametros,
            )

    def test_classifica_produtos_do_cadastro_canonico(self):
        self.assertEqual(
            "RETORNAVEL",
            server._vendas_orcamento_categoria_produto({
                "grupo_estoque": "GFA", "nome_produto": "Cola retornável 600ml",
            }),
        )
        self.assertEqual(
            "PET_600ML",
            server._vendas_orcamento_categoria_produto({
                "grupo_estoque": "PET", "nome_produto": "Cola PET 600ML",
            }),
        )
        self.assertEqual(
            "PET_200ML",
            server._vendas_orcamento_categoria_produto({
                "grupo_estoque": "PET", "produto_base_nome": "UVA 200ML",
            }),
        )
        self.assertEqual(
            "PET_2L",
            server._vendas_orcamento_categoria_produto({
                "grupo_estoque": "PET", "nome_produto": "Uva PET 2L",
            }),
        )

    def test_edicao_so_e_liberada_ao_vendedor_responsavel_ou_admin(self):
        pedido = {"vendedor_usuario_id": 7, "vendedor_login": "lucimar"}
        with server.app.test_request_context(headers={"X-Usuario-Perfil": "admin"}):
            self.assertTrue(server._vendas_orcamento_editavel(pedido))
        with server.app.test_request_context(headers={"X-Usuario-Id": "7", "X-Usuario-Login": "outro"}):
            self.assertTrue(server._vendas_orcamento_editavel(pedido))
        with server.app.test_request_context(headers={"X-Usuario-Id": "8", "X-Usuario-Login": "Lucimar"}):
            self.assertTrue(server._vendas_orcamento_editavel(pedido))
        with server.app.test_request_context(headers={"X-Usuario-Id": "8", "X-Usuario-Login": "rebeca"}):
            self.assertFalse(server._vendas_orcamento_editavel(pedido))

    def test_tela_oferece_edicao_e_atualizacao_do_pedido(self):
        base = Path(__file__).resolve().parents[1]
        script = (base / "script.js").read_text(encoding="utf-8")
        html = (base / "RioBranco.html").read_text(encoding="utf-8")
        self.assertIn("async function editarOrcamentoVendas(id)", script)
        self.assertIn('method: editandoId ? "PUT" : "POST"', script)
        self.assertIn("Atualizar e abrir PDF", script)
        self.assertIn('id="vendasOrcamentoCancelarBtn"', html)
        self.assertIn(">Ações</th>", html)

    def test_gera_pdf_com_pedido_e_memoria_de_calculo(self):
        calculo = server._calcular_orcamento_vendas(
            [{
                "produto_id": 1,
                "produto_nome": "Cola PET 2L",
                "categoria": "PET_2L",
                "unidade": "PCT",
                "quantidade": 10,
                "preco_unitario": 32.45,
                "ordem": 1,
            }],
            self.parametros,
        )
        orcamento = {
            **self.parametros,
            **calculo,
            "codigo": "ORC-2026-000001",
            "data_ref": "2026-08-28",
            "cliente_nome": "Cliente Teste",
            "cidade": "Ourinhos",
            "vendedor_nome": "Vendedor Teste",
            "observacao": "Pagamento combinado.",
        }
        with (
            mock.patch.object(
                server,
                "_build_report_header",
                wraps=server._build_report_header,
            ) as cabecalho,
            mock.patch.object(
                server,
                "_draw_report_footer",
                wraps=server._draw_report_footer,
            ) as rodape,
        ):
            pdf = server._vendas_orcamento_pdf_bytes(orcamento)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1500)
        cabecalho.assert_called_once()
        self.assertTrue(rodape.called)


if __name__ == "__main__":
    unittest.main()
