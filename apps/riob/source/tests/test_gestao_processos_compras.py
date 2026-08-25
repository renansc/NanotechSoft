import unittest
from pathlib import Path

import server
from gestao_processos_compras import purchase_forecast


class GestaoProcessosComprasTests(unittest.TestCase):
    def test_previsao_compra_usa_maior_historico_e_desconta_saldo_e_pedidos(self):
        result = purchase_forecast(
            last_year_month=300,
            recent_months=[240, 270, 210],
            current_week=20,
            elapsed_week_days=4,
            month_days=30,
            current_stock=30,
            open_purchases=10,
            safety_stock=20,
            lead_days=10,
            minimum_lot=0,
            purchase_multiple=5,
        )
        self.assertEqual(300, result["consumo_referencia_mensal"])
        self.assertEqual(70, result["previsao_consumo_semana"])
        self.assertEqual(120, result["necessidade_periodo_entrega"])
        self.assertEqual(80, result["sugestao_compra"])
        self.assertEqual("historico_mensal", result["origem_previsao"])

    def test_previsao_compra_fallback_sem_historico_respeita_lote_e_multiplo(self):
        result = purchase_forecast(
            current_week=12,
            elapsed_week_days=3,
            current_stock=0,
            safety_stock=0,
            lead_days=7,
            minimum_lot=30,
            purchase_multiple=12,
        )
        self.assertEqual(28, result["previsao_consumo_semana"])
        self.assertEqual(36, result["sugestao_compra"])
        self.assertEqual("ritmo_semana", result["origem_previsao"])

    def test_rotas_dos_modulos_estao_registradas(self):
        routes = {rule.rule for rule in server.app.url_map.iter_rules()}
        self.assertIn("/api/processos-internos", routes)
        self.assertIn("/api/processos-internos/relatorio/pdf", routes)
        self.assertIn("/api/compras/solicitacoes", routes)
        self.assertIn("/api/compras/previsao", routes)
        self.assertIn("/api/compras/fornecedores/<int:supplier_id>/contato", routes)
        self.assertIn("/api/compras/relatorio/pdf", routes)
        self.assertIn("/api/dashboard_processos", routes)
        self.assertIn("/api/dashboard_compras", routes)

    def test_interface_separa_operacao_dashboard_relatorio_e_cadastro(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "RioBranco.html").read_text(encoding="utf-8")
        script = (root / "gestao_processos_compras.js").read_text(encoding="utf-8")
        self.assertIn('id="processosInternosKanban"', html)
        self.assertIn('id="comprasKanban"', html)
        self.assertIn('id="comprasViewPrevisao"', html)
        self.assertIn('id="dashViewProcessos"', html)
        self.assertIn('id="dashViewCompras"', html)
        self.assertIn('id="relatoriosViewProcessos"', html)
        self.assertIn('id="relatoriosViewCompras"', html)
        self.assertIn('id="cadastrosViewProcessosTipos"', html)
        self.assertIn('id="cadastrosViewComprasFornecedores"', html)
        self.assertIn("function renderProcessosInternosKanban()", script)
        self.assertIn("function renderComprasKanban()", script)
        self.assertIn("function renderPrevisaoCompras()", script)
        self.assertIn('data-workflow-view="compras"', html)
        self.assertNotIn('data-compras-view="kanban"', html)

    def test_popup_da_compra_exibe_contato_do_fornecedor(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "RioBranco.html").read_text(encoding="utf-8")
        script = (root / "gestao_processos_compras.js").read_text(encoding="utf-8")
        source = Path(server.__file__).read_text(encoding="utf-8")
        module = (root / "gestao_processos_compras.py").read_text(encoding="utf-8")
        for item_id in (
            'id="compraContatoBtn"',
            'id="compraContatoPainel"',
            'id="compraContatoRepresentante"',
            'id="compraContatoTelefone"',
            'id="compraContatoEmail"',
            'id="compraContatoEndereco"',
            'id="compraContatoSalvarBtn"',
            'id="compraContatoStatus"',
        ):
            self.assertIn(item_id, html)
        self.assertIn("function abrirContatoCompra()", script)
        self.assertIn("async function salvarContatoCompra()", script)
        self.assertIn('method:"PATCH"', script)
        self.assertIn("representante_nome VARCHAR(255)", source)
        self.assertIn("COALESCE(cfg.representante_nome,'') AS representante_nome", module)
        self.assertIn("telefone=VALUES(telefone)", module)
        self.assertIn("endereco=VALUES(endereco)", module)
        self.assertIn('methods=["PATCH"]', module)

    def test_recebimento_de_compra_nao_movimenta_estoque_automaticamente(self):
        source = Path(server.__file__).read_text(encoding="utf-8")
        module = (Path(server.__file__).parent / "gestao_processos_compras.py").read_text(encoding="utf-8")
        self.assertNotIn("INSERT INTO estoque_movimentos", module)
        self.assertIn("compras_solicitacoes", source)


if __name__ == "__main__":
    unittest.main()
