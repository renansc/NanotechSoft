"""Catalogo, menu, autorizacao do proxy e headers da sessao unica."""
import json
import unittest
from pathlib import Path
from unittest import mock

import app as portal
import menu_access

USER = {'id':42, 'perfil':'usuario'}
URL = '/apps/riob#custoProduto'


class CustoProdutoAccessTests(unittest.TestCase):
    def setUp(self):
        self.manifest = portal.normalize_app(json.loads((Path(portal.BASE_DIR)/'apps/riob/app.json').read_text()))

    def decision(self, grants, method='GET', xarope=False, dashboard=False, diario=False):
        path = '/apps/riob/api/' + ('custo-diario' if diario else 'custo-produto') + ('/dashboard' if dashboard else '/xarope' if xarope else '/1' if method == 'PUT' and not diario else '')
        with portal.app.test_request_context(path, method=method), \
             mock.patch.object(portal, 'current_user_or_logout', return_value=USER), \
             mock.patch.object(portal, 'allowed_app_keys', return_value={'riob'}), \
             mock.patch.object(portal, 'get_user_permissions', return_value={'riob':grants}):
            result = portal.enforce_app_permission()
            return result[1] if result else 200

    def test_authorized_and_denied_in_both_profiles(self):
        key = menu_access.resource_key(URL)
        for client in ['rio-branco', 'nanotech']:
            with mock.patch.object(portal, 'configured_client_id', return_value=client):
                for method in ['GET','PUT']:
                    for grants, expected in [({'custo_produto'},200), ({key},200), ({'*'},200),
                                             ({'estoque'},403), ({'*','!'+key},403)]:
                        with self.subTest(client=client, method=method, grants=grants):
                            self.assertEqual(expected, self.decision(grants, method))
                with mock.patch.object(portal, 'get_user_permissions', return_value={'riob':{key}}):
                    self.assertIn('custo_produto', portal.allowed_resources_for_app(USER, 'riob'))

    def test_catalog_menu_and_no_implicit_grants(self):
        for client in ['rio-branco','nanotech']:
            with mock.patch.object(portal, 'configured_client_id', return_value=client), \
                 mock.patch.object(portal, 'list_apps', return_value=[self.manifest]):
                catalog = next(a for a in portal.permission_catalog() if a['app_key']=='riob')
                self.assertIn('custo_produto', {r['key'] for r in catalog['recursos']})
                entry = next(e for e in catalog['menus'] if e['url']==URL)
                self.assertIn('Gestao', entry['grupos'])
                self.assertFalse(menu_access.permitted(entry, {'estoque','vendas','frota'}))
                self.assertTrue(menu_access.permitted(entry, {'custo_produto'}))
                dashboard = next(e for e in catalog['menus'] if e['url']=='/apps/riob#custoProdutoDashboard')
                self.assertIn('custo_produto_dashboard', {r['key'] for r in catalog['recursos']})
                self.assertTrue(menu_access.permitted(dashboard, {'custo_produto_dashboard'}))
                self.assertFalse(menu_access.permitted(dashboard, {'custo_produto'}))

    def test_dashboard_has_independent_read_permission(self):
        key = menu_access.resource_key('/apps/riob#custoProdutoDashboard')
        for client in ['rio-branco', 'nanotech']:
            with mock.patch.object(portal, 'configured_client_id', return_value=client):
                for grants, status in [({'custo_produto_dashboard'},200),({key},200),({'*'},200),
                                       ({'custo_produto'},403),({'*','!'+key},403)]:
                    self.assertEqual(status, self.decision(grants, dashboard=True))
                self.assertEqual(403,self.decision({'custo_produto_dashboard'},'PUT'))

    def test_cloud_blocks_formula_writes(self):
        with portal.app.test_request_context('/apps/riob/api/custo-produto/1', method='PUT'), \
             mock.patch.object(portal, 'CLOUD_READ_ONLY', True):
            response, status = portal.enforce_cloud_read_only()
            self.assertEqual(403, status)
            self.assertEqual('cloud_read_only', response.json['code'])

    def test_daily_cost_access_and_count_read_do_not_grant_stock_writes(self):
        key=menu_access.resource_key('/apps/riob#custoDiario')
        for client in ['rio-branco','nanotech']:
            with mock.patch.object(portal,'configured_client_id',return_value=client), mock.patch.object(portal,'list_apps',return_value=[self.manifest]):
                catalog=next(a for a in portal.permission_catalog() if a['app_key']=='riob')
                self.assertIn('custo_diario',{r['key'] for r in catalog['recursos']})
                self.assertTrue(any(e['url']=='/apps/riob#custoDiario' for e in catalog['menus']))
                for grants,status in [({'custo_diario'},200),({key},200),({'custo_produto'},403),({'custo_produto_dashboard'},403),({'*','!'+key},403)]:
                    self.assertEqual(status,self.decision(grants,'PUT',diario=True))
                self.assertEqual(200,self.decision({'custo_produto_dashboard'},dashboard=True,diario=True))
                self.assertEqual(403,self.decision({'custo_diario'},dashboard=True,diario=True))
                denied=menu_access.resource_key('/apps/riob#custoProdutoDashboard')
                self.assertEqual(403,self.decision({'*','!'+denied},dashboard=True,diario=True))
        with portal.app.test_request_context('/apps/riob/api/custo-diario',method='PUT'), mock.patch.object(portal,'CLOUD_READ_ONLY',True):
            self.assertEqual(403,portal.enforce_cloud_read_only()[1])

    def test_xarope_uses_same_permission_and_individual_menu_denial(self):
        key=menu_access.resource_key(URL)
        for grants,status in [({'custo_produto'},200),({key},200),({'estoque'},403),({'*','!'+key},403)]:
            self.assertEqual(status,self.decision(grants,'PUT',xarope=True))
