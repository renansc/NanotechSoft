import json
import unittest
from pathlib import Path
from unittest import mock

import app as portal
import menu_access


ROOT = Path(__file__).resolve().parents[1]


class SpedIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(
            (ROOT / "apps/sped/app.json").read_text(encoding="utf-8")
        )

    def test_manifest_catalog_and_rio_branco_contract(self):
        resources = {item["recurso"] for item in self.manifest["access_resources"]}
        menu_entries = [
            item
            for groups in (self.manifest["menu_groups"], self.manifest["config_groups"])
            for entries in groups.values()
            for item in entries
        ]
        contracts = json.loads(
            (ROOT / "clientes-modulos.json").read_text(encoding="utf-8")
        )
        rio_branco = next(item for item in contracts["clients"] if item["id"] == "rio-branco")
        ecosystem = json.loads(
            (ROOT / "deploy/ecosystem.json").read_text(encoding="utf-8")
        )
        deployments = {item["id"]: item for item in ecosystem["deployments"]}

        self.assertEqual("apps/sped/source", self.manifest["source_dir"])
        self.assertEqual(
            {"dashboard", "importar", "analise", "comparativo", "transacoes", "tributos", "grupos", "config"},
            resources,
        )
        self.assertEqual(resources, {item["recurso"] for item in menu_entries})
        self.assertTrue(all(item["url"].startswith("/apps/sped?view=") for item in menu_entries))
        self.assertIn("sped", {item["slug"] for item in rio_branco["modules"]})
        self.assertIn("sped", deployments["rio-branco"]["requiredModules"])
        self.assertIn("sped", deployments["nanotech"]["requiredModules"])

    def test_routes_use_static_integration_and_single_portal_shell(self):
        routes = {rule.rule for rule in portal.app.url_map.iter_rules()}
        source = (ROOT / "apps/sped/source/index.html").read_text(encoding="utf-8")
        _, content = portal.extract_static_app_integrated(source, "sped")

        self.assertEqual(portal.SPED_DIR, portal.STATIC_APP_DIRS["sped"])
        self.assertEqual("SPED Fiscal", portal.STATIC_APP_NAMES["sped"])
        self.assertIn("/apps/sped", routes)
        self.assertIn("/apps/sped/<path:subpath>", routes)
        self.assertIn("/apps/sped/api/base", routes)
        self.assertIn("/apps/sped/api/configuracoes", routes)
        self.assertIn("/apps/sped/original/<path:subpath>", routes)
        self.assertNotIn("<header>", content)
        self.assertNotIn('<nav class="nav">', content)
        self.assertIn('id="filesBadge"', content)
        self.assertIn("static-sped", content)
        self.assertNotIn(":root{", content)
        self.assertNotIn("body{", content)
        self.assertIn(".static-sped .panel", content)
        self.assertIn("background: transparent", content)
        self.assertIn("background: var(--surface)", content)
        self.assertIn("background: var(--accent)", content)

    @mock.patch.object(portal, "allowed_app_keys", return_value={"sped"})
    def test_server_allows_authorized_user_and_blocks_user_without_access(self, _allowed):
        user = {"id": 9, "nome": "Fiscal", "perfil": "usuario", "ativo": 1}
        with (
            portal.app.test_request_context("/apps/sped?view=imports"),
            mock.patch.object(portal, "current_user_or_logout", return_value=user),
            mock.patch.object(portal, "get_user_permissions", return_value={"sped": {"importar"}}),
        ):
            self.assertIsNone(portal.enforce_app_permission())

        with (
            portal.app.test_request_context("/apps/sped?view=imports"),
            mock.patch.object(portal, "current_user_or_logout", return_value=user),
            mock.patch.object(portal, "get_user_permissions", return_value={}),
        ):
            response, status = portal.enforce_app_permission()

        self.assertEqual(403, status)
        self.assertEqual("app nao liberado para este usuario", response.get_json()["erro"])

    def test_individual_task_block_overrides_general_module_access(self):
        entries = menu_access.entries(self.manifest, "rio-branco")
        imports = next(item for item in entries if item["url"].endswith("view=imports"))
        dashboard = next(item for item in entries if item["url"].endswith("view=dashboard"))
        grants = {"*", "!" + imports["key"]}

        self.assertFalse(menu_access.permitted(imports, grants))
        self.assertTrue(menu_access.permitted(dashboard, grants))
        user = {"id": 9, "nome": "Fiscal", "perfil": "usuario", "ativo": 1}
        with (
            portal.app.test_request_context("/apps/sped?view=imports"),
            mock.patch.object(portal, "allowed_app_keys", return_value={"sped"}),
            mock.patch.object(portal, "current_user_or_logout", return_value=user),
            mock.patch.object(portal, "get_user_permissions", return_value={"sped": grants}),
        ):
            response, status = portal.enforce_app_permission()
        self.assertEqual(403, status)
        self.assertEqual("item do menu nao liberado para este usuario", response.get_json()["erro"])

    def test_source_contains_no_customer_data_or_unimplemented_certificate_call(self):
        source = (ROOT / "apps/sped/source/index.html").read_text(encoding="utf-8")

        self.assertIn("const suggestedGroups2026={}", source)
        self.assertIn("base persistida no servidor", source)
        self.assertIn("sped-multianual-v2", source)
        self.assertIn("/apps/sped/api/", source)
        self.assertIn("/apps/riob/api/custo-produto/sped", source)
        self.assertIn("somente o resumo de itens de entrada C170", source)
        self.assertNotIn("/api/sefaz", source)
        self.assertNotIn("20984401000130", source)
        self.assertNotIn("WHITE RIVER", source.upper())

    def test_transaction_filters_use_separate_select_boxes(self):
        source = (ROOT / "apps/sped/source/index.html").read_text(encoding="utf-8")

        sale_operation = source.split('id="saleOp"', 1)[1].split("</select>", 1)[0]
        self.assertTrue(sale_operation.startswith('><option value="all">Todas</option>'))
        self.assertIn('id="saleProduct"', source)
        self.assertIn('id="saleClient"', source)
        self.assertIn('id="saleDocument"', source)
        self.assertNotIn('id="saleSearch"', source)
        self.assertIn('id="saleSearchStatus" role="status" aria-live="polite"', source)
        self.assertIn('id="saleClear"', source)

    def test_server_validates_persisted_base_and_shared_settings(self):
        base = {
            "name": "efd.txt", "period": "2026-09", "company": "Empresa",
            "companyTaxId": "12.345.678/0001-90", "items": 0,
            "docs": [], "tax": [], "products": [], "apuration": [],
            "inventory": [], "production": [], "inputs": [], "saleItems": [],
        }
        tax_id, period, company, filename, serialized = portal.validate_sped_base(base)
        self.assertEqual("12345678000190", tax_id)
        self.assertEqual("2026-09", period)
        self.assertEqual("Empresa", company)
        self.assertEqual("efd.txt", filename)
        self.assertEqual(base, json.loads(serialized))
        self.assertEqual({"Rotulos": ["A", "B"]}, portal.validate_sped_groups({"Rotulos": ["A", "A", "B"]}))
        self.assertEqual({"2026": {"regime": "real", "pis": "nao_cumulativo"}},
                         portal.validate_sped_settings({"2026": {"regime": "real", "pis": "nao_cumulativo"}}))

    def test_sped_api_access_uses_catalog_resources(self):
        user = {"id": 9, "perfil": "usuario"}
        with mock.patch.object(portal, "get_user_permissions", return_value={"sped": {"grupos"}}):
            self.assertTrue(portal.sped_api_access(user, "grupos"))
            self.assertFalse(portal.sped_api_access(user, "importar"))


if __name__ == "__main__":
    unittest.main()
