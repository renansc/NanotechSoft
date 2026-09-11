import json
import unittest
from pathlib import Path
from unittest import mock

import app as portal


class HeaderNavigationTests(unittest.TestCase):
    def test_integrated_menu_html_is_not_cached(self):
        for path in ("/apps/riob", "/apps/riob/", "/apps/tecnologia"):
            with self.subTest(path=path), portal.app.test_request_context(path):
                response = portal.add_no_cache_headers(portal.Response("menu", mimetype="text/html"))
                self.assertIn("no-store", response.headers["Cache-Control"])
                self.assertIn("must-revalidate", response.headers["Cache-Control"])

    def test_navigation_asset_urls_change_with_content(self):
        with portal.app.test_request_context(), mock.patch.object(Path, "read_bytes", return_value=b"first"):
            first = portal.url_for("static", filename="app.js")
            self.assertEqual(first, portal.url_for("static", filename="app.js"))
            self.assertIn("?v=", portal.url_for("static", filename="style.css"))
            self.assertNotIn("?v=", portal.url_for("static", filename="other.js"))
        with portal.app.test_request_context(), mock.patch.object(Path, "read_bytes", return_value=b"second"):
            self.assertNotEqual(first, portal.url_for("static", filename="app.js"))

    def context(self, role="usuario"):
        return {
            "usuario": {"id": 42, "nome": "Pessoa atual", "login": "pessoa", "perfil": role},
            "config": {"tema": "rio_branco"}, "themes": portal.THEMES,
            "menu": {"modules": [], "dashboards": [], "relatorios": [], "import_export": [], "config": []},
            "client_config": {"source": {"path": "clientes-modulos.json"}},
            "deployment": {"readOnly": False}, "show_portal": True,
        }

    def test_account_shows_current_user_without_admin_controls(self):
        context = self.context()
        with portal.app.test_request_context("/config"), mock.patch.object(
            portal, "current_user_or_logout", return_value=context["usuario"]
        ), mock.patch.object(portal, "portal_context", return_value=context):
            portal.session["usuario_id"] = 42
            html = portal.config_page()
        self.assertIn('id="minha-conta"', html)
        self.assertIn("Pessoa atual", html)
        self.assertNotIn("data-user-admin", html)
        self.assertNotIn("data-edit-current-user", html)
        self.assertNotIn("data-theme-toggle", html)
        self.assertEqual(1, html.count('id="mainMenu"'))
        self.assertLess(html.index('id="mainMenu"'), html.index('</header>'))

    def test_admin_can_open_own_existing_registration(self):
        with portal.app.test_request_context("/config"):
            html = portal.render_template("config.html", **self.context("admin"))
        self.assertIn('data-edit-current-user="42"', html)
        self.assertIn("data-user-admin", html)

    def test_account_requires_valid_session(self):
        with portal.app.test_request_context("/config"):
            self.assertEqual("/login", portal.config_page().location)
        with portal.app.test_request_context("/config"), mock.patch.object(
            portal, "current_user_or_logout", return_value=None
        ), mock.patch.object(portal, "portal_context") as context:
            portal.session["usuario_id"] = 42
            self.assertEqual("/login", portal.config_page().location)
            context.assert_not_called()

    def test_communication_label_preserves_chat_resource(self):
        manifest = json.loads((Path(portal.BASE_DIR) / "apps/riob/app.json").read_text())
        with mock.patch.object(portal, "list_apps", return_value=[manifest]):
            resources = {item["key"]: item["nome"] for item in portal.permission_catalog()[0]["recursos"]}
            self.assertEqual("Comunicacao (chat)", resources["chat"])
            self.assertEqual({"riob": ["chat"]}, portal.validate_user_permissions({"riob": ["chat"]}))

    def test_communication_api_requires_chat_permission(self):
        user = {"id": 42, "perfil": "usuario"}
        for resources, allowed in [({"chat"}, True), ({"vendas"}, False)]:
            with self.subTest(resources=resources), portal.app.test_request_context(
                "/apps/riob/api/chat/mensagens", method="POST"
            ), mock.patch.object(portal, "current_user_or_logout", return_value=user), mock.patch.object(
                portal, "allowed_app_keys", return_value={"riob"}
            ), mock.patch.object(portal, "get_user_permissions", return_value={"riob": resources}):
                result = portal.enforce_app_permission()
                if allowed:
                    self.assertIsNone(result)
                else:
                    self.assertEqual(403, result[1])


if __name__ == "__main__":
    unittest.main()
