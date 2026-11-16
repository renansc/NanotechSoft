"""Autorizacao do relatorio de posicao diaria do estoque."""
import json
from pathlib import Path
import unittest
from unittest import mock

import app as portal
import menu_access


class EstoquePosicaoDiaAccessTests(unittest.TestCase):
    def test_manifest_rota_e_bloqueio_individual(self):
        manifest = portal.normalize_app(json.loads(
            (Path(portal.BASE_DIR) / "apps/riob/app.json").read_text(encoding="utf-8")
        ))
        report = next(
            item for item in menu_access.entries(manifest, "rio-branco")
            if item["url"] == "/apps/riob#relatorios:estoque_posicao_dia"
        )
        self.assertEqual("estoque", report["recurso"])
        self.assertEqual(
            ["/apps/riob#relatorios:estoque_posicao_dia"],
            menu_access.api_destinations(
                "riob", "/apps/riob/api/estoque/relatorio-posicao-dia", "GET"
            ),
        )
        user = {"id": 42, "perfil": "usuario"}
        for grants, expected in (
            ({"estoque"}, 200),
            ({"vendas"}, 403),
            ({report["key"]}, 200),
            ({"estoque", "!" + report["key"]}, 403),
        ):
            with self.subTest(grants=grants), portal.app.test_request_context(
                "/apps/riob/api/estoque/relatorio-posicao-dia?data=2026-10-22"
            ), mock.patch.object(portal, "configured_client_id", return_value="rio-branco"), \
                 mock.patch.object(portal, "current_user_or_logout", return_value=user), \
                 mock.patch.object(portal, "allowed_app_keys", return_value={"riob"}), \
                 mock.patch.object(portal, "get_user_permissions", return_value={"riob": grants}):
                result = portal.enforce_app_permission()
                self.assertEqual(expected, result[1] if result else 200)


if __name__ == "__main__":
    unittest.main()
