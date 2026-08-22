import datetime
import os
import unittest
from pathlib import Path

from vendas_diario import intervalo_semana_iso, parse_report, read_report


class VendasDiarioParserTest(unittest.TestCase):
    def test_calcula_intervalo_operacional_de_domingo_a_sabado(self):
        inicio, fim, semana = intervalo_semana_iso("2026-W33")
        self.assertEqual("2026-08-09", inicio.isoformat())
        self.assertEqual("2026-08-15", fim.isoformat())
        self.assertEqual("2026-W33", semana)

    def test_domingo_de_referencia_abre_a_proxima_semana_iso(self):
        inicio, fim, semana = intervalo_semana_iso(
            referencia=datetime.date(2026, 8, 9)
        )
        self.assertEqual("2026-08-09", inicio.isoformat())
        self.assertEqual("2026-08-15", fim.isoformat())
        self.assertEqual("2026-W33", semana)

    def test_semana_operacional_respeita_virada_do_ano(self):
        inicio, fim, semana = intervalo_semana_iso("2024-W01")
        self.assertEqual("2023-12-31", inicio.isoformat())
        self.assertEqual("2024-01-06", fim.isoformat())
        self.assertEqual("2024-W01", semana)

    def test_rejeita_semana_iso_invalida(self):
        with self.assertRaisesRegex(ValueError, "Semana invalida"):
            intervalo_semana_iso("2026-W54")

    def test_parses_two_column_items_and_negative_order(self):
        text = """
    BEBIDAS WHITE RIVER LTDA                                   31/07/26  10 18     1
                        CONFERENCIA DE PEDIDOS            VENDEDOR     6
    Codigo Tb Vg  Qua Un Descricao                    Valor Total I* Codigo Tb Vg  Qua Un Descricao                    Valor Total I*
      659 ELIAS MAFORTE MEIRELES         PADARIA TALISMA                JD.INTERLAGOS        =>LIVRE        <=
      7000  1  6      4 PT GUARANA RIO BRANCO PET 6X2       34.90      7500 91  6      1 PT ABACAXI RIO BRANCO PET 6X2       34.90
                                       TOTAL DO PEDIDO     174.50                                      PESO BRUTO TOTAL      65.00Kg
    -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
      662 W. C. CINTRA ACOUGUE - ME      CASA DE CARNE FRIVALE          JD. PETROPOLIS       =>LIVRE        <=
    Venda Neg. Motivo : 01 = ESTOCADO
    -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
        """
        parsed = parse_report(text, "modelo.txt")
        self.assertEqual("2026-07-31", parsed["data_ref"])
        self.assertEqual(2, len(parsed["orders"]))
        self.assertEqual(2, len(parsed["orders"][0]["items"]))
        self.assertEqual(91, parsed["orders"][0]["items"][1]["tabela"])
        self.assertEqual("negativa", parsed["orders"][1]["status"])
        self.assertEqual("ESTOCADO", parsed["orders"][1]["motivo"])

    def test_attached_model_is_supported_when_available(self):
        path = "/home/renan/Downloads/10190016.txt"
        if not os.path.exists(path):
            self.skipTest("arquivo de exemplo nao disponivel")
        text, signature = read_report(path)
        parsed = parse_report(text, os.path.basename(path))
        self.assertEqual(64, len(signature))
        self.assertEqual("2026-07-31", parsed["data_ref"])
        self.assertGreater(len(parsed["orders"]), 300)
        self.assertGreater(sum(len(order["items"]) for order in parsed["orders"]), 200)


class VendasDiarioNavigationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source_dir = Path(__file__).resolve().parents[1]
        cls.page = (source_dir / "RioBranco.html").read_text(encoding="utf-8")
        cls.script = (source_dir / "script.js").read_text(encoding="utf-8")

    def test_importacao_fica_no_menu_import_e_kanban_no_workflow(self):
        self.assertIn('data-tab="import"', self.page)
        self.assertIn('data-import-view="sellout"', self.page)
        self.assertIn('>Importar SELLOUT</div>', self.page)
        self.assertNotIn('data-workflow-view="vendas_diario_importar"', self.page)
        self.assertIn('data-workflow-view="vendas_diario"', self.page)
        self.assertNotIn('data-vendas-view="diario"', self.page)
        self.assertIn(
            '<section id="vendasDiarioImportarWorkflow" class="section">',
            self.page,
        )
        self.assertIn('<section id="vendasDiarioWorkflow" class="section">', self.page)

        relatorio = self.page.split('<section id="vendas" class="section">', 1)[1]
        relatorio = relatorio.split('<section id="vendasDiarioImportarWorkflow"', 1)[0]
        self.assertNotIn('id="vendasViewDiario"', relatorio)
        self.assertNotIn('Selecionar TXT do PC', relatorio)
        self.assertNotIn('Ler pastas automaticamente', relatorio)

        importacao = self.page.split('<section id="vendasDiarioImportarWorkflow"', 1)[1]
        importacao = importacao.split('<section id="vendasDiarioWorkflow"', 1)[0]
        self.assertIn('Selecionar TXT do PC', importacao)
        self.assertIn('Ler pastas automaticamente', importacao)
        self.assertIn('id="vendasDiarioBody"', importacao)
        self.assertNotIn('id="vendasDiarioKanbanImportado"', importacao)

        kanban = self.page.split('<section id="vendasDiarioWorkflow"', 1)[1]
        kanban = kanban.split('<!-- =====================================================', 1)[0]
        self.assertIn('id="vendasDiarioKanbanImportado"', kanban)
        self.assertIn("1. Venda TXT recebida", kanban)
        self.assertIn("2. Carga PDF formada", kanban)
        self.assertIn("3. SELLOUT confirmado", kanban)
        self.assertIn("Listar cargas da semana", kanban)
        self.assertIn('type="week" id="vendasDiarioSemana"', kanban)
        self.assertIn('id="vendasDiarioCargasSemanaBody"', kanban)
        self.assertIn('id="vendasDiarioSellout"', importacao)
        self.assertIn('id="vendasDiarioClientes"', importacao)
        self.assertIn('id="vendasDiarioRotas"', importacao)
        self.assertIn("Import / Importar SELLOUT", importacao)
        self.assertNotIn('Selecionar TXT do PC', kanban)
        self.assertNotIn('id="vendasDiarioBody"', kanban)

    def test_navegacao_preserva_links_antigos_no_novo_workflow(self):
        self.assertIn(
            '"vendasDiarioImportarWorkflow"',
            self.script,
        )
        self.assertIn(
            '["importar", "vendas_diario_importar", "importar_vendas_diario"].includes(rawView)',
            self.script,
        )
        self.assertIn('function openImportView(ev, view)', self.script)

    def test_card_resumido_tem_uma_acao_e_salvar_mantem_popup_aberto(self):
        render_card = self.script.split(
            "function _renderCardKanbanVendasDiario(card){", 1
        )[1].split("async function carregarKanbanVendasDiario", 1)[0]
        salvar_card = self.script.split(
            "async function salvarCardVendasDiario(){", 1
        )[1].split("async function excluirCardVendasDiario", 1)[0]

        self.assertEqual(1, render_card.count(">Abrir</button>"))
        self.assertNotIn(">Editar</button>", render_card)
        self.assertNotIn(">Enviar para Liberado</button>", render_card)
        self.assertNotIn("fecharCardVendasDiario()", salvar_card)
        self.assertIn("Card salvo. Você pode enviá-lo para Liberado.", salvar_card)

    def test_card_exibe_dados_logisticos_resolvidos_do_sellout(self):
        render_card = self.script.split(
            "function _renderCardKanbanVendasDiario(card){", 1
        )[1].split("async function carregarKanbanVendasDiario", 1)[0]
        self.assertIn("cidade_resolvida", render_card)
        self.assertIn("rota_resolvida", render_card)
        self.assertIn("mapas_resolvidos", render_card)
        self.assertIn("caminhao_resolvido", render_card)
        self.assertIn("não informado no SELLOUT", render_card)

if __name__ == "__main__":
    unittest.main()
