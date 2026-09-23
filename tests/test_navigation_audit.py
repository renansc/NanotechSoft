import ast
import json
import re
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit, parse_qs

from jinja2 import Environment, FileSystemLoader
from werkzeug.routing import Map, Rule
import app as portal
from tools.audit_navigation import ROOT, inventory, menu_entries, routes


class NavigationAuditTests(unittest.TestCase):
    def test_each_business_route_has_a_menu_or_contextual_action(self):
        links={item['url'] for item in menu_entries()}
        for row in inventory():
            with self.subTest(route=row['rota']):
                self.assertNotEqual('sem_associacao',row['tipo'])
                if row['tipo']=='acao_da_tela':
                    self.assertIn(row['acesso'],links | {'/config','/apps/riob/docs/'})

    def test_menu_pages_match_real_backend_routes_and_static_views(self):
        all_routes=list(routes())
        for item in menu_entries():
            key=item['app'];url=urlsplit(item['url']);path=url.path
            if key=='riob' or not path.startswith('/apps/'):continue
            with self.subTest(url=item['url']):
                if key in ('tecnologia','chamados'):
                    html=(ROOT/'apps'/key/'source/index.html').read_text()
                    views=set(re.findall(r'data-page="([^"]+)"',html))
                    view=url.fragment if key=='tecnologia' else parse_qs(url.query).get('view',['chamados'])[0]
                    if view.startswith('backup-'):view='backup'
                    self.assertIn(view,views)
                    continue
                if key in ('riob-xml','riob-email'):
                    source='apps/riob/source/legacy_services.py'
                    upstream=portal.riob_app_path(key,path.split('/riob',2)[-1] if '/riob/' in path else '')
                else:
                    source='apps/automacao/source/app.py' if key=='automacao' else 'apps/zap/source/app/routes.py'
                    upstream=path.removeprefix('/apps/'+key) or '/'
                rules=[Rule(r['rota'],endpoint=r['funcao'],methods=r['metodos'].split(',')) for r in all_routes if r['arquivo']==source]
                Map(rules).bind('test').match(upstream,method='GET')

    def test_zap_settings_render_only_the_selected_task(self):
        source=ast.parse((ROOT/'apps/zap/source/app/routes.py').read_text())
        sections=next(ast.literal_eval(n.value) for n in source.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SETTINGS_SECTIONS' for t in n.targets))
        env=Environment(loader=FileSystemLoader(ROOT/'apps/zap/source/app/templates'))
        env.globals.update(url_for=lambda endpoint,**kw:'/test',get_flashed_messages=lambda **kw:[],dict=dict,request=type('Request',(),{'script_root':''})())
        template=env.get_template('settings.html')
        for key,label in sections:
            with self.subTest(section=key):
                html=template.render(settings_sections=sections,selected_section=key,is_admin=True,settings_map={},states=[],labels=[],quick_replies=[],settings_rows=[],departments=[],users=[],integration_status=[])
                self.assertEqual([key],re.findall(r'data-settings-section="([^"]+)"',html))
                self.assertIn(label,html)

    def test_new_navigation_preserves_resource_checks(self):
        user={'id':42,'perfil':'usuario'}
        cases=[('/apps/zap/settings?secao=departamentos','zap','settings'),('/apps/zap/api/config/departments','zap','settings'),
          ('/apps/zap/calendar','zap','agenda'),('/apps/zap/docs','zap','docs'),
          ('/apps/riob/api/pontos_venda','riob','pontos_venda'),('/apps/riob/api/processos-internos','riob','processos'),
          ('/apps/riob/api/dashboard_processos','riob','processos'),('/apps/riob/api/dashboard_compras','riob','compras'),
          ('/apps/riob/api/nfe/config','riob','config'),('/apps/riob/api/vendas/diario/cargas-semana','riob','vendas')]
        for path,key,resource in cases:
            for allowed in (True,False):
                permissions={key:{resource if allowed else 'sem_acesso'}}
                with self.subTest(path=path,allowed=allowed), portal.app.test_request_context(path), mock.patch.object(portal,'allowed_app_keys',return_value={'riob','zap'}), mock.patch.object(portal,'current_user_or_logout',return_value=user), mock.patch.object(portal,'get_user_permissions',return_value=permissions):
                    response=portal.enforce_app_permission()
                    self.assertIsNone(response) if allowed else self.assertEqual(403,response[1])

if __name__=='__main__':unittest.main()
