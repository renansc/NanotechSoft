import unittest
from unittest import mock

import app as portal


class PortalAppPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.ensure_database = mock.patch.object(portal, "ensure_database")
        self.ensure_database.start()
        self.addCleanup(self.ensure_database.stop)

    def test_usuario_so_acessa_app_liberado(self):
        usuario = {
            "id": 5,
            "nome": "Senhor",
            "login": "senhor",
            "perfil": "usuario",
            "ativo": 1,
        }

        with (
            mock.patch.object(portal, "current_user_or_logout", return_value=usuario),
            mock.patch.object(
                portal,
                "get_user_permissions",
                return_value={"nanostore": {"*"}},
            ),
            portal.app.test_request_context("/apps/nanostore/api/state"),
        ):
            self.assertIsNone(portal.enforce_app_permission())

        with (
            mock.patch.object(portal, "current_user_or_logout", return_value=usuario),
            mock.patch.object(
                portal,
                "get_user_permissions",
                return_value={"nanostore": {"*"}},
            ),
            portal.app.test_request_context("/apps/automacao"),
        ):
            response, status = portal.enforce_app_permission()

        self.assertEqual(403, status)
        self.assertEqual(
            "app nao liberado para este usuario",
            response.get_json()["erro"],
        )

    def test_rotas_publicas_de_integracao_continuam_liberadas(self):
        for path in (
            "/apps/zap/webhooks/whatsapp",
            "/apps/zap/public/uploads/comprovante.jpg",
            "/apps/pacs/static/app.css",
            "/apps/pacs/share/exame-123",
            "/apps/pacs/api/share/exame-123",
        ):
            with self.subTest(path=path), portal.app.test_request_context(path):
                self.assertIsNone(portal.enforce_app_permission())


if __name__ == "__main__":
    unittest.main()
