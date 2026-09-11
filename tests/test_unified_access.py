import unittest
from unittest import mock
import app as portal


class UnifiedAccessTests(unittest.TestCase):
    def test_portal_only_nanotech_and_render(self):
        for client, expected in [('rio-branco', False), ('senhor', False), ('laboratorio', False), ('nanotech', True), ('cloud', True)]:
            with self.subTest(client=client), mock.patch.object(portal, 'RENDER_RUNTIME', False), mock.patch.object(portal, 'configured_client_id', return_value=client):
                self.assertEqual(expected, portal.deployment_uses_portal())

    def test_entry_respects_permissions_and_contract(self):
        user = {'id': 42, 'perfil': 'usuario'}
        item = {'app_key': 'riob', 'url': '/apps/riob', 'menu_groups': {'vendas': [{'nome': 'Vendas', 'url': '/apps/riob#vendas:orcamento', 'recurso': 'vendas'}]}}
        with mock.patch.object(portal, 'visible_apps_for_user', return_value=[item]), mock.patch.object(portal, 'configured_client_id', return_value='rio-branco'), mock.patch.object(portal, 'get_user_permissions', return_value={'riob': {'vendas'}}):
            self.assertEqual('/apps/riob#vendas:orcamento', portal.application_entry_url(user))
        with mock.patch.object(portal, 'visible_apps_for_user', return_value=[]):
            self.assertIsNone(portal.application_entry_url(user))

    def test_catalog_rejects_unknown_function(self):
        catalog = [{'app_key': 'riob', 'recursos': [{'key': '*'}, {'key': 'vendas'}]}]
        with mock.patch.object(portal, 'permission_catalog', return_value=catalog):
            self.assertEqual({'riob': ['vendas']}, portal.validate_user_permissions({'riob': ['vendas', 'vendas']}))
            for invalid in [{'riob': ['root']}, {'other': ['*']}, [], {'riob': '*'}]:
                with self.assertRaises(ValueError): portal.validate_user_permissions(invalid)

    def test_vendas_cannot_change_configuration(self):
        user = {'id': 42, 'perfil': 'usuario'}
        with mock.patch.object(portal, 'current_user_or_logout', return_value=user), mock.patch.object(portal, 'allowed_app_keys', return_value={'riob'}), mock.patch.object(portal, 'get_user_permissions', return_value={'riob': {'vendas'}}):
            with portal.app.test_request_context('/apps/riob/api/vendas/config', method='PUT'):
                self.assertEqual(403, portal.enforce_app_permission()[1])
            with portal.app.test_request_context('/apps/riob/api/vendas/relatorio'):
                self.assertIsNone(portal.enforce_app_permission())
            with portal.app.test_request_context('/apps/riob/monitor/cameras/'):
                self.assertEqual(403, portal.enforce_app_permission()[1])

    def test_save_without_permissions_preserves_existing_grants(self):
        conn = mock.MagicMock(); cur = conn.cursor.return_value
        cur.fetchone.side_effect = [{'id': 42}, None]
        with portal.app.test_request_context('/api/usuarios/42', method='PUT', json={'nome':'Pessoa', 'login':'pessoa', 'perfil':'usuario'}), mock.patch.object(portal, 'current_admin_or_json_error', return_value=({'id':1}, None)), mock.patch.object(portal, 'get_auth_conn', return_value=conn), mock.patch.object(portal, 'portal_users_payload', return_value={'ok': True}):
            portal.session['usuario_id'] = 1
            self.assertEqual(200, portal.api_update_user(42).status_code)
        self.assertFalse(any('DELETE FROM usuario_app_permissoes' in call.args[0] for call in cur.execute.call_args_list))
        conn.commit.assert_called_once()

    def test_save_permissions_is_transactional_and_scoped(self):
        conn=mock.MagicMock();cur=conn.cursor.return_value;cur.fetchone.side_effect=[{'id':42},None]
        catalog=[{'app_key':'riob','recursos':[{'key':'vendas'}]}]
        with portal.app.test_request_context('/api/usuarios/42',method='PUT',json={'nome':'Pessoa','login':'pessoa','permissoes':{'riob':['vendas']}}), mock.patch.object(portal,'current_admin_or_json_error',return_value=({'id':1},None)),mock.patch.object(portal,'get_auth_conn',return_value=conn),mock.patch.object(portal,'permission_catalog',return_value=catalog),mock.patch.object(portal,'portal_users_payload',return_value={'ok':True}):
            portal.session['usuario_id']=1
            self.assertEqual(200,portal.api_update_user(42).status_code)
        deletes=[call for call in cur.execute.call_args_list if 'DELETE FROM usuario_app_permissoes' in call.args[0]]
        self.assertEqual((42,'riob'),deletes[0].args[1])
        conn.commit.assert_called_once()

if __name__ == '__main__': unittest.main()

class UserCreationTests(unittest.TestCase):
    def test_creation_requires_password_before_database(self):
        with portal.app.test_request_context('/api/usuarios', method='POST', json={'nome':'Pessoa','login':'pessoa'}), mock.patch.object(portal,'current_admin_or_json_error',return_value=({'id':1},None)), mock.patch.object(portal,'get_auth_conn') as connect:
            portal.session['usuario_id']=1
            self.assertEqual(400,portal.api_update_user(None)[1])
            connect.assert_not_called()

    def test_non_admin_cannot_edit_permissions(self):
        with portal.app.test_request_context('/api/usuarios/1',method='PUT',json={'permissoes':{'riob':['*']}}), mock.patch.object(portal,'current_user_or_logout',return_value={'id':42,'perfil':'usuario'}), mock.patch.object(portal,'get_auth_conn') as connect:
            portal.session['usuario_id']=42
            self.assertEqual(403,portal.api_update_user(1)[1])
            connect.assert_not_called()

    def test_failed_permission_save_rolls_back(self):
        conn=mock.MagicMock();cur=conn.cursor.return_value;cur.fetchone.side_effect=[{'id':42},None]
        def execute(sql,*args):
            if 'INSERT INTO usuario_app_permissoes' in sql:raise RuntimeError('DB unavailable')
        cur.execute.side_effect=execute
        with portal.app.test_request_context('/api/usuarios/42',method='PUT',json={'nome':'Pessoa','login':'pessoa','permissoes':{'riob':['vendas']}}),mock.patch.object(portal,'current_admin_or_json_error',return_value=({'id':1},None)),mock.patch.object(portal,'get_auth_conn',return_value=conn),mock.patch.object(portal,'permission_catalog',return_value=[{'app_key':'riob','recursos':[{'key':'vendas'}]}]):
            portal.session['usuario_id']=1
            with self.assertRaises(RuntimeError):portal.api_update_user(42)
        conn.rollback.assert_called_once();conn.commit.assert_not_called()

class ModuleMenuTests(unittest.TestCase):
    def test_groups_operations_without_exposing_forbidden_functions(self):
        user = {'id': 42, 'perfil': 'usuario'}
        apps = [{'app_key': 'riob', 'nome': 'RioB', 'url': '/apps/riob', 'menu_groups': {
            'vendas': [{'nome':'Orcamento', 'url':'/apps/riob#vendas:orcamento', 'recurso':'vendas'}],
            'cadastros': [{'nome':'Produtos', 'url':'/apps/riob#cadastros:estoque_produtos', 'recurso':'estoque'}],
            'relatorios': [{'nome':'Vendas', 'url':'/apps/riob#vendas:relatorio', 'recurso':'vendas'}]}}]
        with mock.patch.object(portal, 'get_user_permissions', return_value={'riob': {'vendas'}}):
            menu = portal.menu_sections(apps, user)
        self.assertEqual(['riob'], [m['key'] for m in menu['modules']])
        self.assertEqual(['Orcamento'], [e['nome'] for e in menu['modules'][0]['entries']])
        self.assertEqual(1, len(menu['relatorios']))
