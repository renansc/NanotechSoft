"""Relatorios otimizados mantem contrato, sessao e escolhas individuais."""
import json
from pathlib import Path
import unittest
from unittest import mock

import app as portal
import menu_access


class VendasReportsAccessTest(unittest.TestCase):
    def test_read_routes_preserve_sales_permission_and_denials(self):
        user = {'id': 42, 'perfil': 'usuario'}
        # A API serve tambem outros relatorios: bloquear todas as entradas irmas.
        manifest = portal.normalize_app(json.loads((Path(portal.BASE_DIR) / 'apps/riob/app.json').read_text()))
        for profile in ['rio-branco', 'nanotech']:
            all_denied = {'*'} | {'!' + entry['key'] for entry in menu_access.entries(manifest, profile)
                                 if entry.get('recurso') == 'vendas'}
            for path in ['/apps/riob/api/vendas/meses',
                         '/apps/riob/api/vendas/relatorio?tipo_relatorio=bonificacoes',
                         '/apps/riob/api/vendas/relatorio?tipo_relatorio=percentual_vendas_anual']:
                for grants, status in [({'vendas'}, 200), ({'estoque'}, 403), (all_denied, 403)]:
                    with self.subTest(profile=profile, path=path, grants=grants), \
                         portal.app.test_request_context(path), \
                         mock.patch.object(portal, 'configured_client_id', return_value=profile), \
                         mock.patch.object(portal, 'current_user_or_logout', return_value=user), \
                         mock.patch.object(portal, 'allowed_app_keys', return_value={'riob'}), \
                         mock.patch.object(portal, 'get_user_permissions', return_value={'riob': grants}):
                        result = portal.enforce_app_permission()
                        self.assertEqual(status, result[1] if result else 200)

    def test_catalog_identifies_monthly_and_annual_without_new_grants(self):
        manifest = portal.normalize_app(json.loads((Path(portal.BASE_DIR) / 'apps/riob/app.json').read_text()))
        for profile in ['rio-branco', 'nanotech']:
            with mock.patch.object(portal, 'configured_client_id', return_value=profile), \
                 mock.patch.object(portal, 'list_apps', return_value=[manifest]):
                catalog = next(app for app in portal.permission_catalog() if app['app_key'] == 'riob')
                resource = next(item for item in catalog['recursos'] if item['key'] == 'vendas')
                self.assertIn('mensais/anuais', str(resource))
                for entry in catalog['menus']:
                    if entry['url'] in ['/apps/riob#vendas:relatorio', '/apps/riob#vendas:relatorio_anual']:
                        self.assertTrue(menu_access.permitted(entry, {'vendas'}))
                        self.assertFalse(menu_access.permitted(entry, {'estoque'}))


if __name__ == '__main__':
    unittest.main()
