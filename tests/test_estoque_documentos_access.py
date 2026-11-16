"""Catalogo e autorizacao da aprovacao de documentos do estoque."""
import json
from pathlib import Path
import unittest
from unittest import mock

import app as portal
import menu_access


class EstoqueDocumentosAccessTests(unittest.TestCase):
    def test_manifest_proxy_e_interface_usam_recurso_individual(self):
        manifest_data = json.loads(
            (Path(portal.BASE_DIR) / "apps/riob/app.json").read_text(encoding="utf-8")
        )
        manifest = portal.normalize_app(manifest_data)
        url = "/apps/riob#estoque:documentos"
        user = {"id": 42, "perfil": "usuario"}

        for profile in ("rio-branco", "nanotech"):
            entry = next(
                item for item in menu_access.entries(manifest, profile)
                if item["url"] == url
            )
            self.assertEqual("estoque_documentos_aprovar", entry["recurso"])

            for grants, expected in (
                ({"estoque_documentos_aprovar"}, 200),
                ({entry["key"]}, 200),
                ({"estoque"}, 403),
                ({"*", "!" + entry["key"]}, 403),
            ):
                with self.subTest(profile=profile, grants=grants), \
                     mock.patch.object(portal, "configured_client_id", return_value=profile), \
                     mock.patch.object(portal, "current_user_or_logout", return_value=user), \
                     mock.patch.object(portal, "allowed_app_keys", return_value={"riob"}), \
                     mock.patch.object(portal, "get_user_permissions", return_value={"riob": grants}):
                    sections = portal.menu_sections([manifest], user)
                    self.assertEqual(
                        expected == 200,
                        any(item["url"] == url for item in sections["estoque"]),
                    )
                    for path, method in (
                        ("/apps/riob/api/estoque/aprovacoes-pdf", "GET"),
                        ("/apps/riob/api/estoque/aprovacoes-pdf/sincronizar", "POST"),
                        ("/apps/riob/api/estoque/aprovacoes-pdf/8", "GET"),
                        ("/apps/riob/api/estoque/aprovacoes-pdf/8/confirmar", "POST"),
                        ("/apps/riob/api/estoque/aprovacoes-pdf/8/rejeitar", "POST"),
                    ):
                        with self.subTest(path=path, method=method), portal.app.test_request_context(path, method=method):
                            result = portal.enforce_app_permission()
                            self.assertEqual(expected, result[1] if result else 200)

            # A fila XML e compartilhada com a tela antiga. Qualquer um dos
            # dois destinos autorizados deve continuar funcionando.
            for grants in ({"estoque_documentos_aprovar"}, {entry["key"]}, {"estoque"}, {"*"}):
                with mock.patch.object(portal, "configured_client_id", return_value=profile), \
                     mock.patch.object(portal, "current_user_or_logout", return_value=user), \
                     mock.patch.object(portal, "allowed_app_keys", return_value={"riob"}), \
                     mock.patch.object(portal, "get_user_permissions", return_value={"riob": grants}):
                    for path, method in (
                        ("/apps/riob/api/estoque/importacoes-xml", "GET"),
                        ("/apps/riob/api/estoque/importacoes-xml/confirmar", "POST"),
                    ):
                        with self.subTest(profile=profile, grants=grants, path=path), portal.app.test_request_context(path, method=method):
                            result = portal.enforce_app_permission()
                            self.assertEqual(200, result[1] if result else 200)

        html = (Path(portal.BASE_DIR) / "apps/riob/source/RioBranco.html").read_text(encoding="utf-8")
        script = (Path(portal.BASE_DIR) / "apps/riob/source/script.js").read_text(encoding="utf-8")
        self.assertIn('data-estoque-view="documentos"', html)
        self.assertIn('id="estoqueAprovacoesPdfBox"', html)
        self.assertIn("sincronizarAprovacoesPdfEstoque", script)
        self.assertIn("confirmarAprovacaoPdfEstoque", script)
        self.assertIn("_verificarBaixaPdfDepoisDeFalha", script)
        self.assertIn('id="estoquePdfRejeitarBtn"', html)
        self.assertIn("rejeitarAprovacaoPdfEstoque", script)
        self.assertIn("rejeitar", json.dumps(manifest_data, ensure_ascii=False).lower())


if __name__ == "__main__":
    unittest.main()
