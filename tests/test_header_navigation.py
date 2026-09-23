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

    def test_deploy_identity_is_shared_by_all_page_templates(self):
        context = self.context()
        for deploy in ('Rio Branco', 'Senhor Shopp', 'Nanotech', 'Render'):
            for template in ('config.html', 'integrated_frame.html', 'integrated_app.html', 'portal.html', 'app_placeholder.html'):
                with self.subTest(deploy=deploy, template=template), portal.app.test_request_context():
                    html = portal.render_template(template, **context, deploy_name=deploy,
                                                  app_nome='XML', frame_url='/apps/riob/embed')
                    self.assertIn('<h1>' + deploy + '</h1>', html)
                    self.assertEqual(1, html.count('data-logout'))
                    self.assertLess(html.index('</nav>'), html.index('data-logout'))
                    self.assertLess(html.index('data-logout'), html.index('</header>'))

    def test_deploy_name_comes_from_selected_contract(self):
        for client_id, name in [('rio-branco', 'Rio Branco'), ('senhor', 'Senhor Shopp'), ('cloud', 'Render')]:
            with self.subTest(client_id=client_id), portal.app.test_request_context(), mock.patch.object(
                portal, 'configured_client_id', return_value=client_id
            ), mock.patch.object(portal, 'client_contracts_payload', return_value={'activeClient': {'nome': name}}), mock.patch.object(
                portal, 'list_apps', return_value=[]
            ), mock.patch.object(portal, 'visible_apps_for_user', return_value=[]), mock.patch.object(
                portal, 'menu_sections', return_value={}
            ), mock.patch.object(portal, 'get_config', return_value={'tema': 'fin-blue'}):
                self.assertEqual(name, portal.portal_context({'id': 42, 'perfil': 'admin'})['deploy_name'])

    def test_documentation_requires_config_and_original_returns_to_shell(self):
        user = {'id': 42, 'perfil': 'usuario'}
        for resources, allowed in [({'config'}, True), ({'*'}, True), ({'vendas'}, False)]:
            for suffix in ('docs/', 'docs/documentacao.html', 'docs/README.md'):
                with self.subTest(resources=resources, suffix=suffix), portal.app.test_request_context(
                    '/apps/riob/' + suffix
                ), mock.patch.object(portal, 'current_user_or_logout', return_value=user), mock.patch.object(
                    portal, 'allowed_app_keys', return_value={'riob'}
                ), mock.patch.object(portal, 'get_user_permissions', return_value={'riob': resources}):
                    result = portal.enforce_app_permission()
                    self.assertIsNone(result) if allowed else self.assertEqual(403, result[1])
        with portal.app.test_request_context('/apps/riob/original'):
            portal.session['usuario_id'] = 42
            self.assertEqual('/apps/riob/', portal.riob_proxy('original').location)

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
