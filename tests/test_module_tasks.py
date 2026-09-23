"""Task shells and compatibility routes, with synthetic data only."""
import json
import re
import unittest
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from unittest import mock
from jinja2 import Environment, FileSystemLoader, select_autoescape
import app as portal

ROOT = Path(__file__).resolve().parents[1]
KEYS = ('tecnologia', 'automacao', 'chamados')


def context(user=None):
    user = user or {'id': 42, 'nome': 'Pessoa teste', 'perfil': 'admin'}
    apps = [portal.normalize_app(json.loads((ROOT/'apps'/key/'app.json').read_text())) for key in KEYS]
    return dict(usuario=user, config={'tema': 'rio_branco'}, deploy_name='Rio Branco', show_portal=False,
                menu=portal.menu_sections(apps, user))


def automation_page(path):
    templates = {'/': 'dashboard', '/maquinas': 'maquinas', '/motores': 'motores',
                 '/sensores/drivers': 'drivers', '/historico': 'historico', '/alarmes': 'alarmes',
                 '/tempo-real': 'tempo_real', '/setores': 'setores', '/documentacao': 'documentacao',
                 '/documentacao/cadastrar': 'documento_cadastro'}
    env = Environment(loader=FileSystemLoader(ROOT/'apps/automacao/source/templates'), autoescape=select_autoescape())
    return env.get_template(templates[path] + '.html').render(
        total_motores=0,total_leituras=0,total_alarmes=0,total_maquinas=0,maquinas_em_alarme=0,
        maquinas=[],motores=[],dados=[],drivers=[],setores=[],catalogo={}).encode()


class ModuleTaskTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in [('ensure_database', None), ('configured_client_id', 'rio-branco'),
                            ('allowed_app_keys', set(KEYS)), ('current_theme_key', 'rio_branco'),
                            ('portal_context', context()), ('current_user_or_logout', {'id':42,'perfil':'usuario'}),
                            ('get_user_permissions', {key:{'*'} for key in KEYS})]:
            self.stack.enter_context(mock.patch.object(portal, name, return_value=value))
        self.client=portal.app.test_client()
        with self.client.session_transaction() as s:s['usuario_id']=42

    def test_old_entrypoints_keep_destination_and_filters(self):
        for key, suffix in [('tecnologia',''),('chamados',''),('automacao',''),('automacao','/motores'),('tecnologia','/styles.css')]:
            with self.subTest(key=key,suffix=suffix):
                response=self.client.get('/apps/'+key+'/original'+suffix+'?view=dashboard')
                self.assertEqual(307,response.status_code)
                self.assertEqual('/apps/'+key+suffix+'?view=dashboard',response.location)
        response=self.client.post('/apps/automacao/original/motor/novo',data={'nome':'teste'})
        self.assertEqual(307,response.status_code)
        self.assertEqual('/apps/automacao/motor/novo',response.location)

    def test_anonymous_restricted_and_disabled_cannot_open_tasks_or_aliases(self):
        for key in KEYS:
            for suffix in ('','/original'):
                path='/apps/'+key+suffix
                with self.subTest(path=path), mock.patch.object(portal,'get_user_permissions',return_value={}):
                    self.assertEqual(403,self.client.get(path).status_code)
                with mock.patch.object(portal,'current_user_or_logout',return_value=None):
                    self.assertEqual('/login',self.client.get(path).location)
                with mock.patch.object(portal,'allowed_app_keys',return_value=set()):
                    self.assertEqual(404,self.client.get(path).status_code)

    def test_manifest_catalog_preserves_existing_resources(self):
        apps=[portal.normalize_app(json.loads((ROOT/'apps'/key/'app.json').read_text())) for key in KEYS]
        with mock.patch.object(portal,'list_apps',return_value=apps):
            catalog={a['app_key']:{r['key'] for r in a['recursos']} for a in portal.permission_catalog()}
        self.assertEqual({'*','documentos','documentos_cadastrar'},catalog['automacao'])
        self.assertEqual({'*','dashboard','equipamentos','historico','config','backup','rede','rede_scan'},catalog['tecnologia'])
        self.assertEqual({'*','dashboard','chamados','agenda','historico','documentos'},catalog['chamados'])
        for item in apps:self.assertNotIn('/original',item['standalone_url'])

    def test_automation_extracts_only_task_from_every_template(self):
        for path in ('/','/maquinas','/motores','/sensores/drivers','/historico','/alarmes','/tempo-real','/setores','/documentacao','/documentacao/cadastrar'):
            with self.subTest(path=path),portal.app.test_request_context():
                style, body=portal.extract_automacao_page(automation_page(path))
                self.assertNotIn('class="sidebar"',body)
                self.assertNotIn('<body',body)
                self.assertNotIn('<title>',body)
                self.assertIn('.automacao-content button',style)
                self.assertNotRegex(style,r'(?m)^button\s*\{')
                self.assertNotRegex(style,r'(?m)^body\s*\{')

    def test_source_tasks_have_links_in_rendered_menu_for_both_profiles(self):
        # Inventario independente dos manifests: telas reais e sidebar original.
        for profile in ('rio-branco', 'nanotech'):
            with self.subTest(profile=profile), mock.patch.object(portal,'configured_client_id',return_value=profile), portal.app.test_request_context():
                html=portal.render_template('_menu.html', **context())
                links={urlsplit(url.replace('&amp;','&')) for url in re.findall(r'href="([^"]+)"',html)}
                for key in ('tecnologia','chamados'):
                    source=(ROOT/'apps'/key/'source/index.html').read_text()
                    views=set(re.findall(r'data-page="([^"]+)"',source))
                    destinations={url.fragment or 'dashboard' if key=='tecnologia' else parse_qs(url.query).get('view',['chamados'])[0]
                                  for url in links if url.path=='/apps/'+key}
                    if key=='tecnologia':
                        self.assertTrue({'backup-visao','backup-planos','backup-agentes'} <= destinations)
                        destinations.add('backup')
                    self.assertFalse(views-destinations,(key,views-destinations))
                source=(ROOT/'apps/automacao/source/templates/base.html').read_text()
                for path in re.findall(r'<a[^>]*href="(/[^"]*)"',source):
                    self.assertIn('/apps/automacao'+path,{url.path for url in links})

    def test_technology_api_requires_the_resource_even_with_direct_url(self):
        cases=[('network','GET','rede'),('network/7','GET','rede'),('backup/jobs','GET','backup'),('backup/jobs/1','PUT','backup'),
               ('backup/jobs/1/run-now','POST','backup'),('backup/agent-script','GET','backup'),
               ('backup/windows-installer','GET','backup'),('link-usage-history','GET','historico'),
               ('history','GET','historico'),('speed-history','GET','historico'),
               ('alerts/config','GET','config'),('alerts/config','PUT','config'),
               ('probe','POST','dashboard'),('speed-test','POST','dashboard'),
               ('devices','POST','equipamentos'),('discover-printers','POST','equipamentos')]
        for path,method,resource in cases:
            for allowed in (True,False):
                with self.subTest(path=path,allowed=allowed),portal.app.test_request_context('/apps/tecnologia/api/'+path,method=method),mock.patch.object(portal,'get_user_permissions',return_value={'tecnologia':{resource if allowed else 'outro'}}):
                    response=portal.enforce_app_permission()
                    self.assertIsNone(response) if allowed else self.assertEqual(403,response[1])
        for resource in ('dashboard','historico','equipamentos','config','backup','rede'):
            with portal.app.test_request_context('/apps/tecnologia/api/overview'),mock.patch.object(portal,'get_user_permissions',return_value={'tecnologia':{resource}}):
                result=portal.enforce_app_permission()
                self.assertEqual(403,result[1]) if resource in {'backup','rede'} else self.assertIsNone(result)

    def test_technology_shell_receives_only_existing_grants(self):
        with mock.patch.object(portal,'get_user_permissions',return_value={'tecnologia':{'backup'}}):
            response=self.client.get('/apps/tecnologia')
        self.assertEqual(200,response.status_code)
        self.assertIn('data-resources="[&quot;backup&quot;]"',response.get_data(as_text=True))

    def test_link_and_backup_shortcuts_follow_existing_user_grants(self):
        user={'id':42,'perfil':'usuario'}
        for profile in ('rio-branco','nanotech'):
            for resource in ('dashboard','backup'):
                with self.subTest(profile=profile,resource=resource),mock.patch.object(portal,'configured_client_id',return_value=profile),mock.patch.object(portal,'get_user_permissions',return_value={'tecnologia':{resource}}),portal.app.test_request_context():
                    html=portal.render_template('_menu.html',**context(user))
                    self.assertEqual(resource=='dashboard','#monitor-link' in html)
                    for view in ('backup-visao','backup-planos','backup-agentes'):
                        self.assertEqual(resource=='backup','#'+view in html)

if __name__=='__main__':unittest.main()
