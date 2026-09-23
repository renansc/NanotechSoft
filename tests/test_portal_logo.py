import base64
from io import BytesIO
import unittest
from unittest import mock

from PIL import Image
import app as portal


class PortalLogoTests(unittest.TestCase):
    def request(self, method="POST", role="usuario", permissions=None, raw=None, cloud=False, logged_in=True, url=None, current=None):
        payload = {}
        if url is not None:
            payload["logo_url"] = url
        if raw is not None:
            payload["logo"] = (BytesIO(raw), "logo.png")
        user = {"id": 42, "nome": "Nanotech", "perfil": role} if logged_in else None
        with mock.patch.object(portal, "ensure_database"), mock.patch.object(
            portal, "current_user_or_logout", return_value=user
        ), mock.patch.object(portal, "get_user_permissions", return_value=permissions or {}), mock.patch.object(
            portal, "get_auth_conn"
        ) as connect, mock.patch.object(portal, "CLOUD_READ_ONLY", cloud), mock.patch.object(
            portal, "get_config", return_value=current or {}
        ):
            client = portal.app.test_client()
            if logged_in:
                with client.session_transaction() as session:
                    session["usuario_id"] = 42
            response = client.open("/api/config/logo", method=method, data=payload)
            return response, connect

    def test_anonymous_and_unauthorized_cannot_write(self):
        for method in ("POST", "DELETE"):
            for logged_in, permissions, status in (
                (False, {}, 401), (True, {}, 403), (True, {"riob": {"*"}}, 403)
            ):
                with self.subTest(method=method, logged_in=logged_in, permissions=permissions):
                    response, connect = self.request(method, permissions=permissions, logged_in=logged_in)
                    self.assertEqual(status, response.status_code)
                    connect.assert_not_called()

    def test_upload_is_persisted_as_normalized_image(self):
        raw = BytesIO()
        Image.new("RGB", (900, 300), "red").save(raw, "JPEG")
        for role, permissions in (("admin", {}), ("usuario", {"sistema": {"logo"}}), ("usuario", {"sistema": {"*"}})):
            with self.subTest(role=role, permissions=permissions):
                response, connect = self.request(role=role, permissions=permissions, raw=raw.getvalue())
                self.assertEqual(200, response.status_code)
                data = response.json["logo_data"]
                with Image.open(BytesIO(base64.b64decode(data.split(",", 1)[1]))) as result:
                    self.assertEqual("PNG", result.format)
                    self.assertLessEqual(result.width, 640)
                    self.assertLessEqual(result.height, 240)
                connect.return_value.cursor.return_value.execute.assert_called_once()
                self.assertEqual((data, ""), connect.return_value.cursor.return_value.execute.call_args.args[1])
                connect.return_value.commit.assert_called_once()

    def test_invalid_and_oversized_uploads_do_not_change_logo(self):
        for raw in (None, b"<svg></svg>", b"x" * (2 * 1024 * 1024 + 1)):
            response, connect = self.request(role="admin", raw=raw)
            self.assertEqual(400, response.status_code)
            connect.assert_not_called()

    def test_remove_and_cloud_write_guard(self):
        response, connect = self.request("DELETE", role="admin")
        self.assertEqual(200, response.status_code)
        self.assertEqual("", response.json["logo_data"])
        connect.return_value.commit.assert_called_once()
        for method in ("POST", "DELETE"):
            response, connect = self.request(method, role="admin", cloud=True)
            self.assertEqual(403, response.status_code)
            self.assertEqual("cloud_read_only", response.json["code"])
            connect.assert_not_called()

    def test_manifest_catalog_and_menu_share_resource(self):
        with mock.patch.object(portal, "list_apps", return_value=[]):
            catalog = portal.permission_catalog()
            self.assertIn({"key": "logo", "nome": "Configurar logo e link do cabecalho"}, catalog[0]["recursos"])
            self.assertEqual({"sistema": ["logo"]}, portal.validate_user_permissions({"sistema": ["logo"]}))

    def test_legacy_config_preserves_theme_without_logo_column(self):
        with mock.patch.object(portal, "get_auth_conn") as connect:
            connect.return_value.cursor.return_value.fetchone.return_value = {"tema": "fin-blue"}
            self.assertEqual({"tema": "fin-blue", "logo_data": "", "logo_url": ""}, portal.get_config())

    def test_url_only_preserves_image_and_removal_preserves_url(self):
        current = {"logo_data": "existing-image", "logo_url": "https://old.example/"}
        for url in ("https://example.com/site?q=1#home", "http://localhost:8080/", ""):
            response, connect = self.request(url=url, permissions={"sistema": {"logo"}}, current=current)
            self.assertEqual(200, response.status_code)
            self.assertEqual("existing-image", response.json["logo_data"])
            self.assertEqual(url, response.json["logo_url"])
            self.assertEqual(("existing-image", url), connect.return_value.cursor.return_value.execute.call_args.args[1])
        response, _ = self.request("DELETE", role="admin", current=current)
        self.assertEqual("", response.json["logo_data"])
        self.assertEqual(current["logo_url"], response.json["logo_url"])

    def test_unsafe_urls_and_unauthorized_url_changes_are_rejected(self):
        for url in ("javascript:alert(1)", "data:text/html,test", "//example.com", "https://", "https://user:pass@example.com",
                    "https://example.com\\test", "https://example.com/\npath", "https://example.com:bad", "https://example.com/" + "x" * 2048):
            response, connect = self.request(role="admin", url=url)
            self.assertEqual(400, response.status_code, url)
            connect.assert_not_called()
        response, connect = self.request(url="https://example.com")
        self.assertEqual(403, response.status_code)
        connect.assert_not_called()

    def test_header_logo_link_and_default_without_image(self):
        for logo, url, expected in (("", "", "https://renansc.github.io/"),
                                    ("", "https://custom.example/", "https://renansc.github.io/"),
                                    ("image", "", "https://renansc.github.io/"),
                                    ("image", "https://custom.example/", "https://custom.example/")):
            with self.subTest(logo=logo, url=url), portal.app.test_request_context():
                html = portal.render_template("_topbar.html", menu={}, usuario={"nome":"Pessoa"},
                                              config={"logo_data":logo, "logo_url":url})
                self.assertIn(f'href="{expected}" target="_blank" rel="noopener noreferrer"', html)
                self.assertIn('data-logo-fallback' + (' hidden' if logo else '') + '>Nanotechsoft</span>', html)

    def test_header_places_user_before_menu_and_logo_after(self):
        for profile in ({"primary": [{"key": "config", "nome": "Config", "groups": []}]}, {}):
            with portal.app.test_request_context():
                html = portal.render_template("_topbar.html", menu=profile,
                    usuario={"nome": "Nanotech", "perfil": "usuario"}, deploy_name="Rio Branco",
                    topbar_subtitle="Rio Branco", config={"logo_data": "data:image/png;base64,test"},
                    system_config=[])
                self.assertEqual(1, html.count("Rio Branco"))
                self.assertLess(html.index("Nanotech"), html.index('id="mainMenu"'))
                self.assertLess(html.index('id="mainMenu"'), html.index('data-topbar-logo'))
                self.assertNotIn('/config#logo', html)
                self.assertIn('data-logout', html)


if __name__ == "__main__":
    unittest.main()
