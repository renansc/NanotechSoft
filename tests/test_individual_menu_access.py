"""Per-menu choices, including denials inside previously granted modules."""
import json
import unittest
from urllib.parse import urlsplit
from pathlib import Path
from unittest import mock
import app as portal
import menu_access as access

USER = {'id': 42, 'perfil': 'usuario'}
ROOT = Path(__file__).resolve().parents[1]
KEYS = ['riob','automacao','tecnologia','chamados','riob-email','riob-xml','zap']


class IndividualMenuTests(unittest.TestCase):
    def setUp(self):
        self.apps = [portal.normalize_app(json.loads((ROOT/'apps'/key/'app.json').read_text())) for key in KEYS]
        patch = mock.patch.object(portal,'configured_client_id',return_value='rio-branco')
        patch.start();self.addCleanup(patch.stop)

    def decision(self, key, path, grants, method='GET'):
        with portal.app.test_request_context(path,method=method),mock.patch.object(portal,'current_user_or_logout',return_value=USER),mock.patch.object(portal,'allowed_app_keys',return_value=set(KEYS)),mock.patch.object(portal,'get_user_permissions',return_value={key:grants}):
            result=portal.enforce_app_permission()
            return result[1] if result else 200

    def test_every_rendered_item_has_a_catalog_choice(self):
        for client in ('rio-branco','nanotech'):
            with mock.patch.object(portal,'configured_client_id',return_value=client),mock.patch.object(portal,'list_apps',return_value=self.apps):
                catalog=portal.permission_catalog()
                urls={access.destination(e['url']) for a in catalog for e in a['menus']}
                menu=portal.menu_sections(self.apps,{'id':1,'perfil':'admin'})
                if client=='rio-branco':rows=[e for s in menu['primary'] for g in s['groups'] for e in g['entries']]
                else:rows=[e for m in menu['modules'] for e in m['entries']]+[e for s in ('dashboards','relatorios','config','import_export') for e in menu[s]]
                for row in rows:self.assertIn(access.destination(row['url']),urls,row['url'])

    def test_each_individual_choice_can_be_denied_with_full_module_grant(self):
        for app in self.apps:
            rows=access.entries(app,'rio-branco')
            for entry in rows:
                grants={'*','!'+entry['key']}
                self.assertFalse(access.permitted(entry,grants),entry['url'])
                for sibling in rows:
                    if sibling['key']!=entry['key']:self.assertTrue(access.permitted(sibling,grants))
                with mock.patch.object(portal,'get_user_permissions',return_value={app['app_key']:grants}):
                    menu=portal.menu_sections([app],USER)
                    links={e['url'] for s in menu['primary'] for g in s['groups'] for e in g['entries']}
                    self.assertNotIn(entry['url'],links)

    def test_direct_routes_and_apis_enforce_selected_item(self):
        cases=[('tecnologia','#ocupacao-link','/api/link-usage-history','GET'),
               ('tecnologia','#rede','/api/network','GET'),
               ('tecnologia','#rede','/api/network/7','GET'),
               ('tecnologia','#backup-agentes','/api/backup/windows-installer','GET'),
               ('automacao','/motores','/motor/novo','POST'),
               ('automacao','/sensores/drivers','/sensores/drivers/1','GET'),
               ('chamados','?view=agenda','?view=agenda','GET'),
               ('chamados','?view=agenda','/api/agenda','GET'),
               ('riob-xml','/riob/config','/riob/config','POST'),
               ('riob-email','/riob/recuperar','/riob/recuperar-conteudo','POST'),
               ('zap','/settings?secao=departamentos','/api/config/departments','POST'),
               ('riob','#config:backup','/api/backup/full','GET'),
               ('riob','#vendas:orcamento','/api/vendas/orcamentos','POST'),
               ('riob','#cadastros:colaboradores','/api/colaboradores','POST')]
        for key,suffix,path,method in cases:
            resource=access.resource_key('/apps/'+key+suffix)
            with self.subTest(key=key,path=path):
                self.assertEqual(403,self.decision(key,'/apps/'+key+path,{'*','!'+resource},method))
                self.assertEqual(200,self.decision(key,'/apps/'+key+path,{resource},method))

    def test_every_menu_with_server_visible_destination_is_independent(self):
        for app in self.apps:
            for entry in access.entries(app,'rio-branco'):
                if urlsplit(entry['url']).fragment:
                    continue
                with self.subTest(url=entry['url']):
                    self.assertEqual(403,self.decision(app['app_key'],entry['url'],{'*','!'+entry['key']}))
                    self.assertEqual(200,self.decision(app['app_key'],entry['url'],{entry['key']}))

    def test_shared_read_does_not_grant_sibling_writes(self):
        grant=access.resource_key('/apps/tecnologia#backup-visao')
        self.assertEqual(200,self.decision('tecnologia','/apps/tecnologia/api/backup/jobs',{grant}))
        self.assertEqual(403,self.decision('tecnologia','/apps/tecnologia/api/backup/jobs',{grant},'POST'))
        grant=access.resource_key('/apps/riob#estoque:contagem')
        self.assertEqual(200,self.decision('riob','/apps/riob/api/estoque/produtos',{grant}))
        self.assertEqual(403,self.decision('riob','/apps/riob/api/estoque/contagens/conferir',{grant},'POST'))

    def test_aliases_share_one_choice(self):
        for a,b in [('/apps/automacao/','/apps/automacao'),('/apps/tecnologia','#unused')]:
            if b=='#unused':b='/apps/tecnologia#dashboard'
            self.assertEqual(access.resource_key(a),access.resource_key(b))
        self.assertEqual(access.resource_key('/apps/chamados'),access.resource_key('/apps/chamados?view=chamados'))
        self.assertEqual(access.resource_key('/apps/zap/original/settings?secao=backup'),access.resource_key('/apps/zap/settings?secao=backup'))

    def test_saving_choices_preserves_legacy_and_unsubmitted_choices(self):
        conn=mock.MagicMock();cur=conn.cursor.return_value;cur.fetchone.side_effect=[{'id':42},None]
        key=access.resource_key('/apps/tecnologia#monitor-link')
        payload={'nome':'Pessoa','login':'pessoa','permissoes_menu':{'tecnologia':{key:False}}}
        with portal.app.test_request_context('/api/usuarios/42',method='PUT',json=payload),mock.patch.object(portal,'current_admin_or_json_error',return_value=({'id':1},None)),mock.patch.object(portal,'get_auth_conn',return_value=conn),mock.patch.object(portal,'list_apps',return_value=self.apps),mock.patch.object(portal,'portal_users_payload',return_value={'ok':True}):
            portal.session['usuario_id']=1
            self.assertEqual(200,portal.api_update_user(42).status_code)
        deletes=[call for call in cur.execute.call_args_list if call.args[0].startswith('DELETE')]
        self.assertEqual(1,len(deletes));self.assertEqual((42,'tecnologia',key),deletes[0].args[1])
        inserts=[call for call in cur.execute.call_args_list if call.args[0].startswith('INSERT')]
        self.assertEqual((42,'tecnologia',key,0),inserts[0].args[1]);conn.commit.assert_called_once()

    def test_catalog_validation_rejects_unknown_and_non_boolean(self):
        with mock.patch.object(portal,'list_apps',return_value=self.apps):
            for value in ({'riob':{'menu:invalid':True}}, {'riob':[]}, {'tecnologia':{access.resource_key('/apps/tecnologia#dashboard'):1}}):
                with self.assertRaises(ValueError):portal.validate_menu_permissions(value)

    def test_denials_are_loaded_and_app_with_all_items_blocked_is_hidden(self):
        rows=access.entries(portal.menu_manifest('tecnologia'),'rio-branco')
        conn=mock.MagicMock()
        conn.cursor.return_value.fetchall.return_value=[{'app_key':'tecnologia','recurso':'*','permitido':1}]+[
            {'app_key':'tecnologia','recurso':row['key'],'permitido':0} for row in rows]
        with portal.app.test_request_context(),mock.patch.object(portal,'get_auth_conn',return_value=conn):
            loaded=portal.get_user_permissions(USER)
            self.assertIn('!'+rows[0]['key'],loaded['tecnologia'])
            self.assertFalse(portal.app_visible_to_user({'app_key':'tecnologia'},USER))
        self.assertEqual(access.resource_key('/apps/tecnologia#backup'),access.resource_key('/apps/tecnologia#backup-visao'))

    def test_zap_bulk_settings_requires_each_affected_menu(self):
        grants={'*','!'+access.resource_key('/apps/zap/settings?secao=backup')}
        for settings,expected in [({'BACKUP_DB_HOST':'test'},False),({'WHATSAPP_TOKEN':'test'},True),
                                  ({'WHATSAPP_TOKEN':'test','BACKUP_DB_HOST':'test'},False)]:
            with portal.app.test_request_context('/apps/zap/api/settings/bulk',method='POST',json={'settings':settings}),mock.patch.object(portal,'get_user_permissions',return_value={'zap':grants}):
                self.assertEqual(expected,portal.enforce_individual_menu_access(USER,'zap'))


if __name__=='__main__':unittest.main()
