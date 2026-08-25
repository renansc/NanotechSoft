import json
import unittest
from unittest import mock
from pathlib import Path

import app as portal


class PortalAppPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.ensure_database = mock.patch.object(portal, "ensure_database")
        self.ensure_database.start()
        self.addCleanup(self.ensure_database.stop)

    def test_usuario_so_acessa_app_liberado(self):
        usuario = {
            "id": 5,
            "nome": "Senhor",
            "login": "senhor",
            "perfil": "usuario",
            "ativo": 1,
        }

        with (
            mock.patch.object(portal, "current_user_or_logout", return_value=usuario),
            mock.patch.object(
                portal,
                "get_user_permissions",
                return_value={"nanostore": {"*"}},
            ),
            portal.app.test_request_context("/apps/nanostore/api/state"),
        ):
            self.assertIsNone(portal.enforce_app_permission())

        with (
            mock.patch.object(portal, "current_user_or_logout", return_value=usuario),
            mock.patch.object(
                portal,
                "get_user_permissions",
                return_value={"nanostore": {"*"}},
            ),
            portal.app.test_request_context("/apps/automacao"),
        ):
            response, status = portal.enforce_app_permission()

        self.assertEqual(403, status)
        self.assertEqual(
            "app nao liberado para este usuario",
            response.get_json()["erro"],
        )

    def test_rotas_publicas_de_integracao_continuam_liberadas(self):
        for path in (
            "/apps/zap/webhooks/whatsapp",
            "/apps/zap/public/uploads/comprovante.jpg",
        ):
            with self.subTest(path=path), portal.app.test_request_context(path):
                self.assertIsNone(portal.enforce_app_permission())

    def test_menu_principal_separa_estoque_de_compras(self):
        usuario = {"id": 1, "perfil": "admin", "ativo": 1}
        apps = [
            {
                "app_key": "riob",
                "nome": "RioB",
                "menu_groups": {
                    "compras": [
                        {"nome": "Importar XML (Bipe) RioB", "url": "/apps/riob#estoque:importar_xml_bipe"},
                        {"nome": "Importar XML Auto RioB", "url": "/apps/riob#estoque:importar_xml_auto"},
                    ],
                    "estoque": [{"nome": "Posicao atual RioB", "url": "/apps/riob#estoque:posicao"}],
                },
                "config_groups": {},
            }
        ]

        secoes = portal.menu_sections(apps, usuario)

        self.assertEqual("Importar XML (Bipe)", secoes["compras"][0]["nome"])
        self.assertEqual("Importar XML Auto", secoes["compras"][1]["nome"])
        self.assertEqual("Posicao atual", secoes["estoque"][0]["nome"])
        self.assertIn("estoque", portal.MENU_SECTIONS)

    def test_email_e_xml_usam_os_servicos_integrados_do_riob(self):
        self.assertNotIn("riob-email", portal.LOCAL_RIOB_APPS)
        self.assertNotIn("riob-xml", portal.LOCAL_RIOB_APPS)
        self.assertEqual("/gestor-emails/", portal.riob_app_path("riob-email"))
        self.assertEqual("/importar-xml/", portal.riob_app_path("riob-xml"))

    def test_manifest_separa_vendas_diario_do_relatorio_de_vendas(self):
        project_dir = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (project_dir / "apps/riob/app.json").read_text(encoding="utf-8")
        )
        groups = manifest["menu_groups"]
        workflow_urls = {item["url"] for item in groups["workflow"]}
        cadastro_urls = {item["url"] for item in groups["cadastros"]}
        estoque_urls = {item["url"] for item in groups["estoque"]}
        import_items = {
            item["nome"]: item["url"] for item in groups["import_export"]
        }

        self.assertIn("/apps/riob#workflow:vendas_diario", workflow_urls)
        self.assertIn("/apps/riob#workflow:compras", workflow_urls)
        self.assertNotIn(
            "/apps/riob#compras:kanban",
            {item["url"] for item in groups["compras"]},
        )
        self.assertEqual(
            "/apps/riob#workflow:vendas_diario_importar",
            import_items["Importar Vendas Diario"],
        )
        self.assertIn(
            {"nome": "Vendas RioB", "url": "/apps/riob#vendas:relatorio"},
            groups["relatorios"],
        )
        self.assertIn(
            {"nome": "Estoque Comprometido RioB", "url": "/apps/riob#relatorios:estoque_comprometido"},
            groups["relatorios"],
        )
        self.assertIn("/apps/riob#cadastros:estoque_produtos", cadastro_urls)
        self.assertIn("/apps/riob#cadastros:estoque_grupos", cadastro_urls)
        self.assertNotIn("/apps/riob#estoque:cadastrar", estoque_urls)

    def test_hash_bridge_redireciona_vendas_diario_para_workflow(self):
        bridge = portal.riob_hash_bridge_script()

        self.assertIn('section === "workflow"', bridge)
        self.assertIn('window.openWorkflowView(null, "vendas_diario")', bridge)
        self.assertIn('window.openWorkflowView(null, "vendas_diario_importar")', bridge)
        self.assertIn('["diario", "vendas_diario", "kanban"]', bridge)
        self.assertIn('section === "relatorios"', bridge)
        self.assertIn('window.openRelatoriosView(null, view || "estoque_comprometido")', bridge)
        self.assertIn('section === "processos"', bridge)
        self.assertIn('window.openProcessosInternos(null)', bridge)
        self.assertIn('section === "compras"', bridge)
        self.assertIn('window.openComprasView(null, view || "previsao")', bridge)


if __name__ == "__main__":
    unittest.main()
