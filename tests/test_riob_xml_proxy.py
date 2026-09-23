import json
import html
import re
import sys
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlsplit

from flask import Flask

import app as portal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/riob/source"))
import legacy_services


class RiobXmlProxyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.user = {"id": 42, "nome": "Pessoa teste", "perfil": "usuario", "ativo": 1}
        self.permissions = {"riob-xml": {"*"}}
        self.requests = []
        backend = Flask("xml-test")
        backend.secret_key = "test-only"
        backend.register_blueprint(legacy_services.XML_BP)
        backend.register_blueprint(legacy_services.EMAIL_BP)
        self.backend = backend.test_client()
        for target, name, options in (
            (portal, "ensure_database", {}),
            (portal, "current_user_or_logout", {"return_value": self.user}),
            (portal, "allowed_app_keys", {"return_value": {"riob-xml", "riob-email"}}),
            (portal, "get_user_permissions", {"side_effect": lambda *_: self.permissions}),
            (portal, "configured_client_id", {"return_value": "rio-branco"}),
            (portal, "portal_context", {"side_effect": self.context}),
            (portal, "RIOB_BASE_URL", {"new": "http://riob-test"}),
            (portal, "apply_standalone_theme", {"side_effect": lambda value: value}),
            (portal, "open_riob_request", {"side_effect": self.open_upstream}),
            (legacy_services, "_rows", {"return_value": []}),
            (legacy_services, "_row", {"return_value": {}}),
        ):
            self.stack.enter_context(mock.patch.object(target, name, **options))
        self.client = portal.app.test_client()
        with self.client.session_transaction() as session:
            session["usuario_id"] = self.user["id"]

    def context(self, *_):
        apps = [portal.normalize_app(json.loads((ROOT / 'apps' / key / 'app.json').read_text()))
                for key in ('riob-xml', 'riob-email')]
        return dict(usuario=self.user, menu=portal.menu_sections(apps, self.user),
                    config={'tema': 'rio_branco'}, deploy_name='Rio Branco', show_portal=False)

    def document(self, response):
        match = re.search(r'srcdoc="([^"]*)"', response.get_data(as_text=True))
        self.assertIsNotNone(match)
        self.assertEqual(1, response.data.count(b'id="mainMenu"'))
        self.assertIn(b'<h1>Rio Branco</h1>', response.data)
        self.assertIn(b'Pessoa teste', response.data)
        document = html.unescape(match[1]).encode()
        self.assertNotIn(b'<nav>', document)
        self.assertNotIn(b'<header>', document)
        self.assertIn(b'<base target="_top"', document)
        return document

    @contextmanager
    def open_upstream(self, req, timeout):
        parsed = urlsplit(req.full_url)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        self.requests.append(path)
        response = self.backend.open(path, method=req.method, data=req.data)
        yield SimpleNamespace(read=lambda: response.data, status=response.status_code,
                              headers=response.headers)

    def test_every_xml_menu_destination_opens_real_blueprint(self):
        manifest = json.loads((ROOT / "apps/riob-xml/app.json").read_text())
        groups = manifest["menu_profiles"]["rio-branco"]["menu_groups"]
        for entries in groups.values():
            for entry in entries:
                with self.subTest(url=entry["url"]):
                    response = self.client.get(entry["url"])
                    self.assertEqual(200, response.status_code)
                    document = self.document(response)
                    self.assertNotIn(b'/apps/riob/importar-xml/', document)
        self.assertIn('/importar-xml/abastecimentos?visao=revisao', self.requests)

    def test_stock_search_csv_and_import_links_keep_xml_scope(self):
        response = self.client.get('/apps/riob-xml/riob/estoque?q=PET')
        self.assertEqual(200, response.status_code)
        self.assertIn('/importar-xml/estoque?q=PET', self.requests)
        self.assertIn(b'href="/apps/riob-xml/riob/estoque/exportar"', self.document(response))
        connection = mock.Mock()
        cursor = connection.cursor.return_value
        cursor.description = [('id',), ('descricao_produto',)]
        cursor.fetchall.return_value = [(1, 'PET')]
        with mock.patch.object(legacy_services, '_conn', return_value=connection):
            csv = self.client.get('/apps/riob-xml/riob/estoque/exportar')
        self.assertEqual(200, csv.status_code)
        self.assertIn('text/csv', csv.content_type)
        self.assertIn(b'1;PET', csv.data)
        index = self.client.get('/apps/riob-xml/riob')
        self.assertIn(b'fetch("/apps/riob-xml/riob/importar-com-progresso"', self.document(index))
        self.assertIn(b'fetch("/apps/riob-xml/riob/status-importacao/"', self.document(index))

    def test_empty_upload_redirect_stays_in_xml_module(self):
        response = self.client.post('/apps/riob-xml/riob', data={})
        self.assertEqual(302, response.status_code)
        self.assertEqual('/apps/riob-xml/riob/', response.location)

    def test_email_menu_destinations_use_their_own_blueprint(self):
        self.permissions = {"riob-email": {"operacao", "backup"}}
        manifest = json.loads((ROOT / "apps/riob-email/app.json").read_text())['menu_profiles']['rio-branco']
        paths = {entry['url'] for kind in ('menu_groups', 'config_groups') for entries in manifest[kind].values() for entry in entries}
        with mock.patch.object(legacy_services, '_storage_used_bytes', return_value=0), mock.patch.object(legacy_services, '_email_accounts', return_value=[]):
            for path in paths:
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(200, response.status_code)
                    self.document(response)
                    self.assertNotIn(b'/apps/riob/gestor-emails/', response.data)
                    self.assertIn(b'/apps/riob-email/riob/', response.data)
        self.assertIn('/gestor-emails/config', self.requests)
        self.assertIn('/gestor-emails/importacao', self.requests)

    def test_nested_navigation_and_preview_do_not_create_another_shell(self):
        response = self.client.get('/apps/riob-xml/riob/estoque?q=PET', headers={'Sec-Fetch-Dest': 'iframe'})
        self.assertEqual(200, response.status_code)
        self.assertNotIn(b'<nav>', response.data)
        self.assertNotIn(b'id="mainMenu"', response.data)
        self.assertIn(b'<base target="_top"', response.data)
        with portal.app.test_request_context('/apps/riob-email/riob/email/1/conteudo'):
            preview = b'<html><body>Mensagem isolada</body></html>'
            self.assertEqual(preview, portal.integrate_riob_module_page(preview, self.user))

    def test_unauthorized_anonymous_and_disabled_deploy_never_reach_backend(self):
        paths = ('estoque', 'abastecimentos?visao=revisao', 'arquivos', 'config',
                 'estoque/exportar', 'importar-com-progresso')
        self.permissions = {"riob": {"estoque"}}
        for suffix in paths:
            path = '/apps/riob-xml/riob/' + suffix
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(403, response.status_code)
        self.permissions = {"riob-xml": {"*"}}
        with mock.patch.object(portal, 'current_user_or_logout', return_value=None):
            response = self.client.get('/apps/riob-xml/riob/estoque')
            self.assertEqual(302, response.status_code)
            self.assertEqual('/login', response.location)
        with mock.patch.object(portal, 'allowed_app_keys', return_value={'riob'}):
            response = self.client.get('/apps/riob-xml/riob/estoque')
            self.assertEqual(404, response.status_code)
        self.assertEqual([], self.requests)


if __name__ == '__main__':
    unittest.main()
