import json
import importlib.util
import unittest
from pathlib import Path


HAS_FLASK = importlib.util.find_spec("flask") is not None
portal = __import__("app") if HAS_FLASK else None


PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAS_FLASK, "Flask nao instalado")
class FinanceiroFavorecidosTests(unittest.TestCase):
    def test_estado_financeiro_persiste_colecao_de_favorecidos(self):
        state = portal.default_finance_state()
        self.assertIn("favorecidos", state)
        self.assertIn("favorecidos", portal.FINANCEIRO_COLLECTIONS)

        state["favorecidos"] = [{
            "id": "fav_1",
            "nome": "Fornecedor",
            "pixKey": "+5544999999999",
        }]
        normalized = portal.normalize_finance_state(state)
        self.assertEqual("fav_1", normalized["favorecidos"][0]["id"])

    def test_manifest_libera_aba_no_grupo_cadastros(self):
        manifest = json.loads((PROJECT / "apps/financeiro/app.json").read_text(encoding="utf-8"))
        entries = manifest["menu_groups"]["cadastros"]
        self.assertTrue(any(item.get("recurso") == "cadastros" for item in entries))
        self.assertIn("cadastros", portal.FINANCEIRO_VIEWS)

    def test_tela_reutiliza_favorecido_no_contas_a_pagar(self):
        markup = (PROJECT / "apps/financeiro/source.html").read_text(encoding="utf-8")
        source = (PROJECT / "apps/financeiro/static/app.js").read_text(encoding="utf-8")
        for expected in (
            'id="view-cadastros"',
            'id="modalFavorecido"',
            'id="favAccessUrl"',
            'id="tFavorecido"',
            'id="parcelasPdfFavorecido"',
            'id="tBankAccount"',
        ):
            self.assertIn(expected, markup)
        self.assertIn("function applyFavorecidoToTitulo", source)
        self.assertIn("function syncFavorecidoPaymentToLinkedTitles", source)
        self.assertIn("function normalizeExternalAccessUrl", source)
        self.assertIn("Acessar site", source)
        self.assertIn("Ver PDF", source)
        self.assertIn("pendingAttachmentFile", source)
        self.assertIn("favorecidoId", source)
        self.assertIn("Ver dados bancários", source)

    def test_importacao_pdf_reutiliza_favorecido_cadastrado(self):
        source = (PROJECT / "apps/financeiro/static/app.js").read_text(encoding="utf-8")

        self.assertIn('$("#parcelasPdfFavorecido").innerHTML', source)
        self.assertIn('$("#parcelasPdfFavorecido").addEventListener("change"', source)
        self.assertIn('item.id === $("#parcelasPdfFavorecido").value', source)
        self.assertIn('favorecidoId: favorecido?.id || ""', source)
        self.assertIn('pixKey: favorecido?.pixKey || ""', source)
        self.assertIn('bankAccount: favorecido?.bankAccount || ""', source)


if __name__ == "__main__":
    unittest.main()
