import json
from pathlib import Path
import unittest
from unittest import mock

import app as portal
import menu_access


class ManutencaoTxtAccessTests(unittest.TestCase):
    def test_import_routes_require_maintenance_menu_access(self):
        manifest = portal.normalize_app(
            json.loads((Path(portal.BASE_DIR) / "apps/riob/app.json").read_text())
        )
        user = {"id": 42, "perfil": "usuario"}
        for profile in ("rio-branco", "nanotech"):
            entry = next(
                item
                for item in menu_access.entries(manifest, profile)
                if item["url"] == "/apps/riob#gestaofrota:manutencao"
            )
            cases = (
                ({"frota"}, 200),
                ({entry["key"]}, 200),
                ({"vendas"}, 403),
                ({"*", "!" + entry["key"]}, 403),
            )
            for route in (
                "/apps/riob/api/manutencoes/importacoes-txt/preview",
                "/apps/riob/api/manutencoes/importacoes-txt",
            ):
                for grants, expected in cases:
                    with (
                        self.subTest(profile=profile, route=route, grants=grants),
                        portal.app.test_request_context(route, method="POST"),
                        mock.patch.object(portal, "configured_client_id", return_value=profile),
                        mock.patch.object(portal, "current_user_or_logout", return_value=user),
                        mock.patch.object(portal, "allowed_app_keys", return_value={"riob"}),
                        mock.patch.object(portal, "get_user_permissions", return_value={"riob": grants}),
                    ):
                        result = portal.enforce_app_permission()
                        self.assertEqual(expected, result[1] if result else 200)


if __name__ == "__main__":
    unittest.main()
