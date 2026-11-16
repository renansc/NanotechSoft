"""Acesso dos relatorios de frota segue o destino individual existente."""
import json
from pathlib import Path
import unittest
from unittest import mock

import app as portal
import menu_access


class FrotaRelatorioAccessTests(unittest.TestCase):
    def test_apis_respeitam_recurso_e_bloqueio_individual(self):
        manifest = portal.normalize_app(json.loads(
            (Path(portal.BASE_DIR) / "apps/riob/app.json").read_text(encoding="utf-8")
        ))
        user = {"id": 42, "perfil": "usuario"}
        for profile in ("rio-branco", "nanotech"):
            report = next(
                item for item in menu_access.entries(manifest, profile)
                if item["url"] == "/apps/riob#gestaofrota:relatorios"
            )
            endpoints = [
                "/apps/riob/api/frota_relatorio/mensal?mes=2026-10",
                "/apps/riob/api/frota_relatorio/consumo-rodagem?data_inicio=2026-10-01&data_fim=2026-10-31",
            ]
            for endpoint in endpoints:
                self.assertEqual(
                    ["/apps/riob#gestaofrota:relatorios"],
                    menu_access.api_destinations("riob", endpoint.split("?", 1)[0], "GET"),
                )
                cases = [
                    ({"frota"}, 200),
                    ({"estoque"}, 403),
                    ({report["key"]}, 200),
                    ({"frota", "!" + report["key"]}, 403),
                ]
                for grants, expected in cases:
                    with self.subTest(profile=profile, endpoint=endpoint, grants=grants), \
                         portal.app.test_request_context(endpoint), \
                         mock.patch.object(portal, "configured_client_id", return_value=profile), \
                         mock.patch.object(portal, "current_user_or_logout", return_value=user), \
                         mock.patch.object(portal, "allowed_app_keys", return_value={"riob"}), \
                         mock.patch.object(portal, "get_user_permissions", return_value={"riob": grants}):
                        result = portal.enforce_app_permission()
                        self.assertEqual(expected, result[1] if result else 200)


if __name__ == "__main__":
    unittest.main()
