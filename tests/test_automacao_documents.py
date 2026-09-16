import io
import json
from pathlib import Path
import unittest
from unittest import mock
import urllib.error
from email.message import Message

import app as portal


class AutomationDocumentAccessTests(unittest.TestCase):
    def test_anonymous_disabled_deploy_and_cloud_writes_are_blocked(self):
        paths = ('/apps/automacao/documentacao/cadastrar', '/apps/automacao/documentacao/arquivos/1')
        for path in paths:
            with portal.app.test_request_context(path), mock.patch.object(portal, 'allowed_app_keys', return_value={'automacao'}), mock.patch.object(portal, 'current_user_or_logout', return_value=None):
                self.assertEqual('/login', portal.enforce_app_permission().location)
            with portal.app.test_request_context(path), mock.patch.object(portal, 'allowed_app_keys', return_value=set()):
                self.assertEqual(404, portal.enforce_app_permission()[1])
        with portal.app.test_request_context(paths[0], method='POST'), mock.patch.object(portal, 'CLOUD_READ_ONLY', True):
            response, status = portal.enforce_cloud_read_only()
            self.assertEqual(403, status)
            self.assertEqual('cloud_read_only', response.json['code'])

    def test_resource_checks_cover_upload_read_download_and_legacy_alias(self):
        user = {"id": 42, "perfil": "usuario"}
        for alias in ('', '/original'):
            for resources in ({'*'}, {'documentos'}, {'documentos_cadastrar'}, {'outro'}, set()):
                cases = [('/documentacao/cadastrar', 'GET', bool(resources & {'*', 'documentos_cadastrar'})),
                         ('/documentacao/cadastrar', 'POST', bool(resources & {'*', 'documentos_cadastrar'})),
                         ('/documentacao', 'GET', bool(resources & {'*', 'documentos', 'documentos_cadastrar'})),
                         ('/documentacao/arquivos/1', 'GET', bool(resources & {'*', 'documentos', 'documentos_cadastrar'})),
                         ('/static/documentos/protocolo-comunicacao-laser-cyklop-n8-v1.2.pdf', 'GET', bool(resources & {'*', 'documentos', 'documentos_cadastrar'})),
                         ('/api/maquinas/impressora-laser-cyklop/leituras', 'POST', '*' in resources),
                         ('/motor/novo', 'POST', '*' in resources)]
                for suffix, method, allowed in cases:
                    path = '/apps/automacao' + alias + suffix
                    with self.subTest(path=path, method=method, resources=resources), portal.app.test_request_context(path, method=method), mock.patch.object(portal, 'configured_client_id', return_value='rio-branco'), mock.patch.object(portal, 'allowed_app_keys', return_value={'automacao'}), mock.patch.object(portal, 'current_user_or_logout', return_value=user), mock.patch.object(portal, 'get_user_permissions', return_value={'automacao': resources}):
                        result = portal.enforce_app_permission()
                        self.assertIsNone(result) if allowed else self.assertEqual(403, result[1])

    def test_registration_is_in_cadastros_and_not_config(self):
        manifest = json.loads((Path(portal.BASE_DIR) / 'apps/automacao/app.json').read_text())
        url = '/apps/automacao/documentacao/cadastrar'
        user = {'id': 42, 'perfil': 'usuario'}
        for profile in ('rio-branco', 'nanotech'):
            with mock.patch.object(portal, 'configured_client_id', return_value=profile):
                definition = portal.app_menu_definition(portal.normalize_app(manifest))
                self.assertIn(url, {entry['url'] for entry in definition['menu_groups']['cadastros']})
                self.assertNotIn(url, {entry['url'] for entries in definition.get('config_groups', {}).values() for entry in entries})
                self.assertEqual('cadastros', portal.automacao_active_page('documentacao/cadastrar'))
                for resources, allowed in (({'documentos_cadastrar'}, True), ({'documentos'}, False), ({'*'}, True)):
                    with mock.patch.object(portal, 'get_user_permissions', return_value={'automacao': resources}), portal.app.test_request_context():
                        menu = portal.menu_sections([portal.normalize_app(manifest)], user)
                        html = portal.render_template('_menu.html', menu=menu, usuario=user)
                        self.assertEqual(allowed, url in html)

    def test_upload_proxy_preserves_multipart_and_redirects_to_document_list(self):
        headers = Message()
        headers['Content-Type'] = 'text/html'
        headers['Location'] = '/documentacao?cadastrado=1'
        upstream = urllib.error.HTTPError('http://localhost/documentacao/cadastrar', 303, 'See Other', headers, io.BytesIO(b''))
        opener = mock.Mock()
        opener.open.side_effect = upstream
        with portal.app.test_request_context('/apps/automacao/documentacao/cadastrar', method='POST', data={'titulo': 'Teste', 'arquivo': (io.BytesIO(b'%PDF'), 'manual.pdf')}), mock.patch.object(portal, 'ensure_automacao_app', return_value=True), mock.patch.object(portal.urllib.request, 'build_opener', return_value=opener), mock.patch.object(portal, 'portal_context', return_value={}):
            response = portal.automacao_proxy_response('documentacao/cadastrar')
        self.assertEqual(303, response.status_code)
        self.assertEqual('/apps/automacao/documentacao?cadastrado=1', response.location)
        req = opener.open.call_args.args[0]
        self.assertIn('multipart/form-data', req.headers['Content-type'])
        self.assertIn(b'filename="manual.pdf"', req.data)


if __name__ == '__main__':
    unittest.main()
