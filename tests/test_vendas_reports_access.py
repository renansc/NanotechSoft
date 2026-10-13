"""Relatorios otimizados mantem contrato, sessao e escolhas individuais."""
import json
from pathlib import Path
import unittest
from unittest import mock

import app as portal
import menu_access


class VendasReportsAccessTest(unittest.TestCase):
    def test_folder_read_status_uses_manual_import_permission(self):
        manifest = portal.normalize_app(json.loads((Path(portal.BASE_DIR) / 'apps/riob/app.json').read_text()))
        user = {'id': 42, 'perfil': 'usuario'}
        for profile in ['rio-branco', 'nanotech']:
            entry = next(
                item for item in menu_access.entries(manifest, profile)
                if item['url'] == '/apps/riob#workflow:vendas_diario_importar'
            )
            for path in ['/apps/riob/api/vendas/diario/importar',
                         '/apps/riob/api/vendas/diario/status-leitura']:
                for grants, status in [({'vendas'}, 200), ({'estoque'}, 403), ({entry['key']}, 200)]:
                    method = 'POST' if path.endswith('/importar') else 'GET'
                    with self.subTest(profile=profile, path=path, grants=grants), \
                         portal.app.test_request_context(path, method=method), \
                         mock.patch.object(portal, 'configured_client_id', return_value=profile), \
                         mock.patch.object(portal, 'current_user_or_logout', return_value=user), \
                         mock.patch.object(portal, 'allowed_app_keys', return_value={'riob'}), \
                         mock.patch.object(portal, 'get_user_permissions', return_value={'riob': grants}):
                        result = portal.enforce_app_permission()
                        self.assertEqual(status, result[1] if result else 200)

    def test_pdvs_import_is_in_data_and_has_separate_permission(self):
        manifest = portal.normalize_app(json.loads((Path(portal.BASE_DIR) / 'apps/riob/app.json').read_text()))
        user = {'id':42,'perfil':'usuario'}
        for profile in ['rio-branco','nanotech']:
            entry = next(e for e in menu_access.entries(manifest,profile) if e['url']=='/apps/riob#vendas:pdvs_totais')
            self.assertEqual('vendas_pdvs',entry['recurso'])
            for method, suffix in [('GET',''),('POST',''),('POST','/conferir')]:
                for grants, status in [({'vendas_pdvs'},200),({'vendas'},403),({'*','!'+entry['key']},403),({entry['key']},200)]:
                    with self.subTest(profile=profile,method=method,grants=grants), \
                         portal.app.test_request_context('/apps/riob/api/vendas/pdvs-totais'+suffix,method=method), \
                         mock.patch.object(portal,'configured_client_id',return_value=profile), \
                         mock.patch.object(portal,'current_user_or_logout',return_value=user), \
                         mock.patch.object(portal,'allowed_app_keys',return_value={'riob'}), \
                         mock.patch.object(portal,'get_user_permissions',return_value={'riob':grants}):
                        result=portal.enforce_app_permission()
                        self.assertEqual(status,result[1] if result else 200)

    def test_read_routes_preserve_sales_permission_and_denials(self):
        user = {'id': 42, 'perfil': 'usuario'}
        # A API serve tambem outros relatorios: bloquear todas as entradas irmas.
        manifest = portal.normalize_app(json.loads((Path(portal.BASE_DIR) / 'apps/riob/app.json').read_text()))
        for profile in ['rio-branco', 'nanotech']:
            all_denied = {'*'} | {'!' + entry['key'] for entry in menu_access.entries(manifest, profile)
                                 if entry.get('recurso') == 'vendas'}
            for path in ['/apps/riob/api/vendas/meses',
                         '/apps/riob/api/vendas/relatorio?tipo_relatorio=bonificacoes',
                         '/apps/riob/api/vendas/relatorio?tipo_relatorio=percentual_vendas_anual',
                         '/apps/riob/api/vendas/relatorio?tipo_relatorio=variacao_preco',
                         '/apps/riob/api/vendas/relatorio?tipo_relatorio=grupos_embalagem',
                         '/apps/riob/api/vendas/relatorio?tipo_relatorio=grupos_embalagem&data_inicio=2026-09-01&data_fim=2026-10-02&vendedor=VENDEDOR&cliente=PDV&grupos=PET%202L',
                         '/apps/riob/api/vendas/relatorio?tipo_relatorio=preco_medio',
                         '/apps/riob/api/vendas/relatorio/preco-medio/pdf',
                         '/apps/riob/api/vendas/diario/relatorio',
                         '/apps/riob/api/vendas/diario/dashboard']:
                for grants, status in [({'vendas'}, 200), ({'estoque'}, 403), (all_denied, 403)]:
                    with self.subTest(profile=profile, path=path, grants=grants), \
                         portal.app.test_request_context(path), \
                         mock.patch.object(portal, 'configured_client_id', return_value=profile), \
                         mock.patch.object(portal, 'current_user_or_logout', return_value=user), \
                         mock.patch.object(portal, 'allowed_app_keys', return_value={'riob'}), \
                         mock.patch.object(portal, 'get_user_permissions', return_value={'riob': grants}):
                        result = portal.enforce_app_permission()
                        self.assertEqual(status, result[1] if result else 200)

    def test_daily_report_has_own_catalog_entry_and_independent_denial(self):
        manifest = portal.normalize_app(json.loads((Path(portal.BASE_DIR) / 'apps/riob/app.json').read_text()))
        user = {'id': 42, 'perfil': 'usuario'}
        for profile in ['rio-branco', 'nanotech']:
            entries = menu_access.entries(manifest, profile)
            report = next(e for e in entries if e['url'] == '/apps/riob#vendas:relatorio_diario')
            dashboard = next(e for e in entries if e['url'] == '/apps/riob#dashboard:vendas_diario')
            for denied, allowed in [(report, dashboard), (dashboard, report)]:
                grants = {'vendas', '!' + denied['key']}
                for path, status in [('/apps/riob/api/vendas/diario/relatorio', 403 if denied is report else 200),
                                     ('/apps/riob/api/vendas/diario/dashboard', 403 if denied is dashboard else 200)]:
                    with self.subTest(profile=profile, path=path, denied=denied['key']), \
                         portal.app.test_request_context(path), \
                         mock.patch.object(portal, 'configured_client_id', return_value=profile), \
                         mock.patch.object(portal, 'current_user_or_logout', return_value=user), \
                         mock.patch.object(portal, 'allowed_app_keys', return_value={'riob'}), \
                         mock.patch.object(portal, 'get_user_permissions', return_value={'riob': grants}):
                        result = portal.enforce_app_permission()
                        self.assertEqual(status, result[1] if result else 200)

    def test_sales_menu_groups_reports_inside_one_entry(self):
        manifest = portal.normalize_app(json.loads((Path(portal.BASE_DIR) / 'apps/riob/app.json').read_text()))
        destinations = {'/apps/riob#vendas:' + view for view in
                        ['relatorio_diario', 'relatorio_anual', 'variacao_preco', 'grupos_embalagem', 'preco_medio']}
        for profile in ['rio-branco', 'nanotech']:
            for user in [{'id': 1, 'perfil': 'admin'}, {'id': 42, 'perfil': 'usuario'}]:
                with self.subTest(profile=profile, user=user), \
                     mock.patch.object(portal, 'configured_client_id', return_value=profile), \
                     mock.patch.object(portal, 'app_visible_to_user', return_value=True), \
                     mock.patch.object(portal, 'get_user_permissions', return_value={'riob': {'vendas'}}):
                    reports = portal.menu_sections([manifest], user)['relatorios']
                    links = {entry['url'] for entry in reports}
                    self.assertFalse(destinations & links)
                    self.assertEqual(1, sum(e['url'] == '/apps/riob#vendas:relatorio' for e in reports))
                    self.assertEqual('Vendas', next(e['nome'] for e in reports if e['url'] == '/apps/riob#vendas:relatorio'))
                    # Mover para abas nao apaga controles nem bloqueios ja salvos.
                    catalog_links = {entry['url'] for entry in menu_access.entries(manifest, profile)}
                    self.assertTrue(destinations <= catalog_links)

    def test_catalog_identifies_monthly_and_annual_without_new_grants(self):
        manifest = portal.normalize_app(json.loads((Path(portal.BASE_DIR) / 'apps/riob/app.json').read_text()))
        for profile in ['rio-branco', 'nanotech']:
            with mock.patch.object(portal, 'configured_client_id', return_value=profile), \
                 mock.patch.object(portal, 'list_apps', return_value=[manifest]):
                catalog = next(app for app in portal.permission_catalog() if app['app_key'] == 'riob')
                resource = next(item for item in catalog['recursos'] if item['key'] == 'vendas')
                self.assertIn('mensais/anuais', str(resource))
                self.assertIn('RioB/CLT/autonomos', str(resource))
                self.assertIn('grupos de embalagem com filtro de grupos e PDVs em popup', str(resource))
                self.assertIn('PDVs e preco medio em popup com ordenacao por valor e nome', str(resource))
                for entry in catalog['menus']:
                    if entry['url'] in ['/apps/riob#vendas:relatorio', '/apps/riob#vendas:relatorio_anual', '/apps/riob#vendas:relatorio_diario']:
                        self.assertTrue(menu_access.permitted(entry, {'vendas'}))
                        self.assertFalse(menu_access.permitted(entry, {'estoque'}))

    def test_single_report_grant_keeps_one_reachable_sales_menu(self):
        manifest = portal.normalize_app(json.loads((Path(portal.BASE_DIR) / 'apps/riob/app.json').read_text()))
        user = {'id': 42, 'perfil': 'usuario'}
        for profile in ['rio-branco', 'nanotech']:
            for view in ['relatorio_diario', 'relatorio_anual', 'variacao_preco', 'grupos_embalagem', 'preco_medio']:
                url = '/apps/riob#vendas:' + view
                grants = {menu_access.resource_key(url)}
                with self.subTest(profile=profile, view=view), \
                     mock.patch.object(portal, 'configured_client_id', return_value=profile), \
                     mock.patch.object(portal, 'app_visible_to_user', return_value=True), \
                     mock.patch.object(portal, 'visible_apps_for_user', return_value=[manifest]), \
                     mock.patch.object(portal, 'get_user_permissions', return_value={'riob': grants}):
                    reports = portal.menu_sections([manifest], user)['relatorios']
                    self.assertEqual([('Vendas', url)], [(e['nome'], e['url']) for e in reports])
                    self.assertEqual(url, portal.application_entry_url(user))
                    main = next(e for e in menu_access.entries(manifest, profile) if e['url'] == '/apps/riob#vendas:relatorio')
                    self.assertFalse(menu_access.permitted(main, grants))

    def test_annual_ranking_and_popup_require_annual_permission(self):
        user = {'id':42,'perfil':'usuario'}
        annual = menu_access.resource_key('/apps/riob#vendas:relatorio_anual')
        dashboard = menu_access.resource_key('/apps/riob#dashboard:vendas_anual')
        cases = [({annual},True,False),({dashboard},False,True),({'estoque'},False,False),
                 ({'vendas'},True,True),({'*','!'+annual},False,True),({'*','!'+dashboard},True,False)]
        for profile in ['rio-branco','nanotech']:
            for grants, allowed, dash_allowed in cases:
                for query, expected in [
                    ('tipo_relatorio=percentual_vendas_anual',allowed),
                    ('tipo=percentual-anual',allowed),
                    ('tipo_relatorio=vendas_anual&visao=anual_clientes',allowed),
                    ('tipo_relatorio=percentual_vendas_anual&visao=anual_clientes&vendedor=A&cliente=B&detalhe=1&pagina=2',allowed),
                    ('tipo_relatorio=percentual_vendas_anual&visao=anual_clientes&detalhe=1&origem=dashboard',allowed),
                    ('tipo_relatorio=bonificacoes&visao=anual_clientes',allowed),
                    ('tipo_relatorio=percentual_vendas_anual&origem=dashboard',dash_allowed)]:
                    with self.subTest(profile=profile,query=query,grants=grants), \
                         portal.app.test_request_context('/apps/riob/api/vendas/relatorio?'+query), \
                         mock.patch.object(portal,'configured_client_id',return_value=profile), \
                         mock.patch.object(portal,'current_user_or_logout',return_value=user), \
                         mock.patch.object(portal,'allowed_app_keys',return_value={'riob'}), \
                         mock.patch.object(portal,'get_user_permissions',return_value={'riob':grants}):
                        result=portal.enforce_app_permission()
                        self.assertEqual(200 if expected else 403,result[1] if result else 200)

    def test_unified_prices_preserve_each_section_and_pdf_permission(self):
        user = {'id': 42, 'perfil': 'usuario'}
        price = menu_access.resource_key('/apps/riob#vendas:preco_medio')
        variation = menu_access.resource_key('/apps/riob#vendas:variacao_preco')
        dashboard = menu_access.resource_key('/apps/riob#dashboard:variacao_preco')
        cases = [({price, variation}, True, True, False), ({price}, True, False, False),
                 ({variation}, False, True, False), ({'estoque'}, False, False, False),
                 ({'*', '!' + price}, False, True, True),
                 ({'*', '!' + variation}, True, False, True),
                 ({'*', '!' + variation, '!' + price}, False, False, True),
                 ({dashboard}, False, False, True)]
        for profile in ['rio-branco', 'nanotech']:
            for grants, can_price, can_variation, can_dashboard in cases:
                paths = [('/api/vendas/relatorio?tipo_relatorio=preco_medio&visao=precos_cidade', can_price),
                         ('/api/vendas/relatorio?tipo_relatorio=preco_medio&visao=precos_cidade&detalhe=1&cidade=X&produto=P&grupo=G', can_price),
                         ('/api/vendas/relatorio?tipo_relatorio=variacao_preco&visao=precos_cidade', can_variation),
                         ('/api/vendas/relatorio?tipo_relatorio=variacao_preco&visao=precos_cidade&detalhe=1&cidade=X&produto=P&grupo=G', can_variation),
                         ('/api/vendas/relatorio?tipo_relatorio=variacao_preco&visao=precos_cidade&origem=dashboard', can_variation),
                         ('/api/vendas/relatorio?tipo_relatorio=preco_medio', can_price),
                         ('/api/vendas/relatorio?tipo=preco-medio', can_price),
                         ('/api/vendas/relatorio?tipo_relatorio=preco_medio_cidade', can_price),
                         ('/api/vendas/relatorio/preco-medio/pdf', can_price),
                         ('/api/vendas/relatorio?tipo_relatorio=variacao_preco', can_variation),
                         ('/api/vendas/relatorio?tipo=variacao-venda', can_variation),
                         ('/api/vendas/relatorio?tipo_relatorio=variacaopreco', can_variation),
                         ('/api/vendas/relatorio?tipo_relatorio=variacao_preco&origem=dashboard', can_dashboard)]
                if price in grants or variation in grants:
                    paths.append(('/api/vendas/meses', True))
                for path, permitted in paths:
                    with self.subTest(profile=profile, grants=grants, path=path), \
                         portal.app.test_request_context('/apps/riob' + path), \
                         mock.patch.object(portal, 'configured_client_id', return_value=profile), \
                         mock.patch.object(portal, 'current_user_or_logout', return_value=user), \
                         mock.patch.object(portal, 'allowed_app_keys', return_value={'riob'}), \
                         mock.patch.object(portal, 'get_user_permissions', return_value={'riob': grants}):
                        result = portal.enforce_app_permission()
                        self.assertEqual(200 if permitted else 403, result[1] if result else 200)
            manifest = portal.menu_manifest('riob')
            for entry in menu_access.entries(manifest, profile):
                if entry['key'] in {price, variation}:
                    self.assertIn('preço med.varia', entry['nome'])


if __name__ == '__main__':
    unittest.main()
