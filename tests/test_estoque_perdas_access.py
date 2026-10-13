import json
from pathlib import Path
import unittest
from unittest import mock
import app as portal
import menu_access


class PerdasAccessTest(unittest.TestCase):
    def test_menu_catalog_and_server_require_loss_permission(self):
        manifest=portal.normalize_app(json.loads((Path(portal.BASE_DIR)/'apps/riob/app.json').read_text()))
        url='/apps/riob#estoque:perdas'; key=menu_access.resource_key(url)
        user={'id':42,'perfil':'usuario'}
        for profile in ['rio-branco','nanotech']:
            entry=next(e for e in menu_access.entries(manifest,profile) if e['url']==url)
            self.assertEqual('estoque_perdas',entry['recurso'])
            for grants,status in [({'estoque_perdas'},200),({key},200),({'estoque'},403),({'vendas'},403),({'*','!'+key},403)]:
                with mock.patch.object(portal,'configured_client_id',return_value=profile), \
                     mock.patch.object(portal,'current_user_or_logout',return_value=user), \
                     mock.patch.object(portal,'allowed_app_keys',return_value={'riob'}), \
                     mock.patch.object(portal,'get_user_permissions',return_value={'riob':grants}):
                    sections=portal.menu_sections([manifest],user)
                    self.assertEqual(status==200,any(e['url']==url for e in sections['estoque']))
                    for suffix,method in [('', 'GET'),('/produtos','GET'),('/conferir','POST'),('/1/finalizar','POST')]:
                        with self.subTest(profile=profile,grants=grants,suffix=suffix),portal.app.test_request_context('/apps/riob/api/estoque/perdas'+suffix,method=method):
                            result=portal.enforce_app_permission()
                            self.assertEqual(status,result[1] if result else 200)
                    if status==200:
                        self.assertIn('estoque_perdas',portal.allowed_resources_for_app(user,'riob'))


if __name__=='__main__':unittest.main()
