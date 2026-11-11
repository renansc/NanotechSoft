"""Catalogo, menu, autorizacao do proxy e headers da sessao unica."""
import json
import shutil
import subprocess
import tempfile
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

    def decision(self, grants, method='GET', xarope=False, dashboard=False, diario=False, composto=False, rateio=False, sped=False, produto=False, restaurar=False):
        suffix = '/dashboard' if dashboard else '/rateio' if rateio else '/sped' if sped else '/xaropes-compostos' if composto else '/xarope' if xarope else '/produtos/1/restaurar' if produto and restaurar else '/produtos/1' if produto else '/1' if method in {'PUT','DELETE'} and not diario else ''
        path = '/apps/riob/api/' + ('custo-diario' if diario else 'custo-produto') + suffix
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
                for method in ['GET','PUT','DELETE']:
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
                resource=next(r for r in catalog['recursos'] if r['key']=='custo_produto')
                self.assertIn('valores provisorios',resource['nome'])
                self.assertIn('rateios',resource['nome'])
                self.assertIn('pacotes',resource['nome'])
                self.assertIn('embalagens por unidade',resource['nome'])
                self.assertIn('referencias de preco por NF-e e SPED',resource['nome'])
                self.assertIn('autocomplete de apresentacoes PET por sabor',resource['nome'])
                self.assertIn('conversoes',resource['nome'])
                self.assertIn('caldeira por hora',resource['nome'])
                self.assertIn('combustivel por 44 h semanais',resource['nome'])
                self.assertIn('abastecimentos',resource['nome'])
                self.assertIn('exclusao e recadastro de formulas',resource['nome'])
                self.assertIn('remocao e restauracao de itens da lista de producao',resource['nome'])
                entry = next(e for e in catalog['menus'] if e['url']==URL)
                self.assertIn('Gestao', entry['grupos'])
                self.assertFalse(menu_access.permitted(entry, {'estoque','vendas','frota'}))
                self.assertTrue(menu_access.permitted(entry, {'custo_produto'}))
                rateio = next(e for e in catalog['menus'] if e['url']=='/apps/riob#config:custos_producao')
                self.assertTrue(menu_access.permitted(rateio, {'custo_produto'}))
                self.assertFalse(menu_access.permitted(rateio, {'config'}))
                dashboard = next(e for e in catalog['menus'] if e['url']=='/apps/riob#custoProdutoDashboard')
                self.assertIn('custo_produto_dashboard', {r['key'] for r in catalog['recursos']})
                dashboard_resource=next(r for r in catalog['recursos'] if r['key']=='custo_produto_dashboard')
                self.assertIn('cards',dashboard_resource['nome'])
                self.assertIn('agua',dashboard_resource['nome'])
                self.assertIn('rateios',dashboard_resource['nome'])
                self.assertIn('embalagens',dashboard_resource['nome'])
                self.assertIn('relatorio PDF por sabor',dashboard_resource['nome'])
                self.assertIn('XML/SPED',dashboard_resource['nome'])
                self.assertTrue(menu_access.permitted(dashboard, {'custo_produto_dashboard'}))
                self.assertFalse(menu_access.permitted(dashboard, {'custo_produto'}))
                report = next(e for e in catalog['menus'] if e['url']=='/apps/riob#relatorios:custo_produto')
                self.assertEqual('custo_produto_dashboard', report['recurso'])
                self.assertTrue(menu_access.permitted(report, {'custo_produto_dashboard'}))
                self.assertFalse(menu_access.permitted(report, {'custo_produto'}))

    def test_cost_frontend_has_valid_javascript_syntax(self):
        browser = shutil.which('google-chrome') or shutil.which('chromium')
        if not browser:
            self.skipTest('Chrome/Chromium nao instalado')
        javascript = (Path(portal.BASE_DIR) / 'apps/riob/source/custo_produto.js').read_text(encoding='utf-8')
        page = (
            '<body><script>'
            f"try {{ new Function({json.dumps(javascript)}); document.body.textContent='ok'; }} "
            "catch (error) { document.body.textContent=error.name + ':' + error.message; }"
            '</script></body>'
        )
        with tempfile.TemporaryDirectory(prefix='custo-produto-js-') as temp_dir:
            page_path = Path(temp_dir) / 'test.html'
            page_path.write_text(page, encoding='utf-8')
            result = subprocess.run(
                [browser, '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--dump-dom', page_path.as_uri()],
                capture_output=True, text=True, timeout=30, check=True,
            )
        self.assertIn('<body>ok</body>', result.stdout)

    def test_dashboard_has_independent_read_permission(self):
        key = menu_access.resource_key('/apps/riob#custoProdutoDashboard')
        for client in ['rio-branco', 'nanotech']:
            with mock.patch.object(portal, 'configured_client_id', return_value=client):
                for grants, status in [({'custo_produto_dashboard'},200),({key},200),({'*'},200),
                                       ({'custo_produto'},403),({'*','!'+key},403)]:
                    self.assertEqual(status, self.decision(grants, dashboard=True))
                self.assertEqual(403,self.decision({'custo_produto_dashboard'},'PUT'))

    def test_sped_price_sync_uses_existing_cost_editor_permission(self):
        for client in ['rio-branco', 'nanotech']:
            with mock.patch.object(portal, 'configured_client_id', return_value=client):
                self.assertEqual(200, self.decision({'custo_produto'}, 'POST', sped=True))
                self.assertEqual(403, self.decision({'custo_produto_dashboard'}, 'POST', sped=True))

    def test_cloud_blocks_formula_writes(self):
        for method in ('PUT','DELETE'):
            with portal.app.test_request_context('/apps/riob/api/custo-produto/1', method=method), \
                 mock.patch.object(portal, 'CLOUD_READ_ONLY', True):
                response, status = portal.enforce_cloud_read_only()
                self.assertEqual(403, status)
                self.assertEqual('cloud_read_only', response.json['code'])

    def test_product_list_visibility_uses_cost_permission_and_cloud_block(self):
        for method,restaurar in [('DELETE',False),('POST',True)]:
            for grants,status in [({'custo_produto'},200),({'custo_produto_dashboard'},403),({'estoque'},403)]:
                self.assertEqual(status,self.decision(grants,method,produto=True,restaurar=restaurar))
            path='/apps/riob/api/custo-produto/produtos/1' + ('/restaurar' if restaurar else '')
            with portal.app.test_request_context(path,method=method), mock.patch.object(portal,'CLOUD_READ_ONLY',True):
                self.assertEqual(403,portal.enforce_cloud_read_only()[1])

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
            self.assertEqual(status,self.decision(grants,'POST',composto=True))
            self.assertEqual(status,self.decision(grants,'PUT',rateio=True))
