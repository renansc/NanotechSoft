import json
import unittest
from pathlib import Path
from unittest import mock

import app as portal


class MenuPdfTests(unittest.TestCase):
    def setUp(self):
        self.client = mock.patch.object(portal, "configured_client_id", return_value="rio-branco")
        self.client.start()
        self.addCleanup(self.client.stop)
        contract = json.loads((Path(portal.BASE_DIR) / "clientes-modulos.json").read_text())
        self.keys = {m["slug"] for c in contract["clients"] if c["id"] == "rio-branco" for m in c["modules"]}
        self.apps = [json.loads((Path(portal.BASE_DIR) / "apps" / key / "app.json").read_text()) for key in self.keys]

    def test_header_order_and_module_groups(self):
        menu = portal.menu_sections(self.apps, {"id": 1, "perfil": "admin"})
        self.assertEqual(["Dash", "Cadastro", "Relatorio", "Dados", "Config", "Workflow", "Monitor", "Estoque", "Gestao", "Docs"], [s["nome"] for s in menu["primary"]])
        with portal.app.test_request_context():
            html = portal.render_template("_menu.html", menu=menu, usuario={"perfil": "admin"})
        self.assertEqual(1, html.count('id="mainMenu"'))
        self.assertIn("#estoque:contagem", html)
        self.assertIn("#relatorios:orcamentos", html)
        self.assertIn("/riob/backup", html)
        self.assertIn("/riob/historico", html)
        self.assertIn("/riob/recuperar", html)
        self.assertNotIn("module-riob-chat", html)
        for section in menu["primary"]:
            self.assertTrue(all(g["nome"] and g["entries"] for g in section["groups"]))

    def test_other_clients_keep_original_menu(self):
        with mock.patch.object(portal, "configured_client_id", return_value="nanotech"):
            menu = portal.menu_sections(self.apps, {"id": 1, "perfil": "admin"})
        self.assertNotIn("primary", menu)
        self.assertTrue(menu["modules"])

    def test_sales_user_sees_report_without_stock_or_email(self):
        with mock.patch.object(portal, "get_user_permissions", return_value={"riob": {"vendas", "vendas_orcamentos_relatorio"}}):
            menu = portal.menu_sections(self.apps, {"id": 42, "perfil": "usuario"})
        links = [e["url"] for s in menu["primary"] for g in s["groups"] for e in g["entries"]]
        self.assertIn("/apps/riob#relatorios:orcamentos", links)
        self.assertNotIn("/apps/riob#estoque:contagem", links)
        self.assertFalse(any("riob-email" in url for url in links))

    def test_new_routes_preserve_server_resource_checks(self):
        cases = [
            ("/apps/riob/api/vendas/orcamentos/relatorio", "GET", {"riob": {"vendas_orcamentos_relatorio"}}, True),
            ("/apps/riob/api/vendas/orcamentos/relatorio", "GET", {"riob": {"estoque"}}, False),
            ("/apps/riob/api/estoque/posicao", "GET", {"riob": {"estoque_contagem"}}, True),
            ("/apps/riob/api/estoque/posicao", "GET", {"riob": {"vendas"}}, False),
            ("/apps/riob-email/riob/backup/download", "POST", {"riob-email": {"*"}}, True),
            ("/apps/riob-email/riob/backup/download", "POST", {"riob": {"vendas"}}, False),
            ("/apps/riob/api/vendas/orcamentos/relatorio", "GET", {"riob": {"vendas"}}, False),
            ("/apps/riob/api/vendas/orcamentos/1/pdf", "GET", {"riob": {"vendas_orcamentos_relatorio"}}, True),
            ("/apps/riob/api/estoque/produtos/1/ajuste", "POST", {"riob": {"estoque_contagem"}}, False),
            ("/apps/riob-email/riob/backup/download", "POST", {"riob-email": {"backup"}}, True),
            ("/apps/riob-email/riob/importar", "POST", {"riob-email": {"backup"}}, False),
            ("/apps/riob-email/riob/backup/download", "POST", {"riob-email": {"operacao"}}, False),
            ("/apps/riob/gestor-emails/backup/download", "POST", {"riob": {"vendas"}}, False),
        ]
        for path, method, permissions, allowed in cases:
            with self.subTest(path=path, allowed=allowed), portal.app.test_request_context(path, method=method), mock.patch.object(portal, "current_user_or_logout", return_value={"id": 42, "perfil": "usuario"}), mock.patch.object(portal, "allowed_app_keys", return_value=self.keys), mock.patch.object(portal, "get_user_permissions", return_value=permissions):
                result = portal.enforce_app_permission()
                self.assertIsNone(result) if allowed else self.assertEqual(403, result[1])

    def test_disabled_modules_block_admin_and_embedded_alias(self):
        paths = [f"/apps/{key}/" for key in ("financeiro", "nanoponto", "nanostore", "riob-cameras", "riob-esxi")]
        paths += ["/apps/riob/monitor/cameras/", "/apps/riob/monitor/esxi/api/status", "/api/finance/attachments"]
        for path in paths:
            with self.subTest(path=path), portal.app.test_request_context(path), mock.patch.object(portal, "allowed_app_keys", return_value=self.keys), mock.patch.object(portal, "current_user_or_logout", return_value={"id": 1, "perfil": "admin"}):
                self.assertEqual(404, portal.enforce_app_permission()[1])

    def test_catalog_preserves_all_previous_resources(self):
        with mock.patch.object(portal, "list_apps", return_value=self.apps):
            catalog = {a["app_key"]: {r["key"] for r in a["recursos"]} for a in portal.permission_catalog()}
        for app in self.apps:
            for key in ("menu_groups", "config_groups"):
                for items in app.get(key, {}).values():
                    for item in items:
                        if item.get("recurso"):
                            self.assertIn(item["recurso"], catalog[app["app_key"]])


if __name__ == "__main__":
    unittest.main()
