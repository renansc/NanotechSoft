"""Plano de contas central, interface e controle de acesso."""
import json
from pathlib import Path
import unittest
from unittest import mock

import app as portal
import menu_access


ROOT = Path(__file__).resolve().parents[1]
USER = {"id": 42, "perfil": "usuario", "ativo": 1}


class FinanceiroContabilidadeTests(unittest.TestCase):
    def test_manifest_interface_e_schema_expoem_recurso_contabil(self):
        manifest = portal.normalize_app(json.loads(
            (ROOT / "apps/financeiro/app.json").read_text(encoding="utf-8")
        ))
        entries = menu_access.entries(manifest, "rio-branco")
        entry = next(item for item in entries if item["url"] == "/apps/financeiro?view=contabilidade")
        self.assertEqual("contabilidade", entry["recurso"])

        markup = (ROOT / "apps/financeiro/source.html").read_text(encoding="utf-8")
        source = (ROOT / "apps/financeiro/static/app.js").read_text(encoding="utf-8")
        schema = (ROOT / "sql/schema.sql").read_text(encoding="utf-8")
        for expected in (
            'id="view-contabilidade"', 'id="tbPlanoContas"',
            'id="tbVinculosContabeis"', 'id="modalContaContabil"',
        ):
            self.assertIn(expected, markup)
        self.assertIn("loadAccountingData", source)
        self.assertIn("saveAccountingBindings", source)
        self.assertIn("CREATE TABLE IF NOT EXISTS contabil_plano_contas", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS contabil_vinculos", schema)

    def test_validacao_da_conta_e_da_hierarquia(self):
        account = portal.normalize_accounting_account({
            "code": "1.1.01", "name": "Caixa", "classification": "ativo",
            "nature": "devedora", "analytical": True,
        })
        self.assertEqual("ATIVO", account["classification"])
        self.assertEqual("DEVEDORA", account["nature"])

        with self.assertRaisesRegex(ValueError, "código e o nome"):
            portal.normalize_accounting_account({})
        with self.assertRaisesRegex(ValueError, "Classificação"):
            portal.normalize_accounting_account({
                "code": "1", "name": "Inválida", "classification": "OUTRA", "nature": "DEVEDORA"
            })
        with self.assertRaisesRegex(ValueError, "ciclo"):
            portal.validate_accounting_parent([
                {"id": "pai", "parentId": "filha"},
                {"id": "filha", "parentId": ""},
            ], "filha", "pai")

    def test_api_e_menu_exigem_recurso_individual(self):
        manifest = portal.normalize_app(json.loads(
            (ROOT / "apps/financeiro/app.json").read_text(encoding="utf-8")
        ))
        entry = next(item for item in menu_access.entries(manifest, "rio-branco")
                     if item["url"] == "/apps/financeiro?view=contabilidade")
        client = portal.app.test_client()
        with client.session_transaction() as session:
            session["usuario_id"] = USER["id"]
        snapshot = {"accounts": [], "registries": [], "summary": {}, "warnings": [], "classifications": [], "natures": []}
        for grants, expected in (({"contabilidade"}, 200), ({entry["key"]}, 200), ({"config"}, 403)):
            with self.subTest(grants=grants), \
                 mock.patch.object(portal, "ensure_database"), \
                 mock.patch.object(portal, "configured_client_id", return_value="rio-branco"), \
                 mock.patch.object(portal, "current_user_or_logout", return_value=USER), \
                 mock.patch.object(portal, "allowed_app_keys", return_value={"financeiro"}), \
                 mock.patch.object(portal, "app_visible_to_user", return_value=True), \
                 mock.patch.object(portal, "get_user_permissions", return_value={"financeiro": grants}), \
                 mock.patch.object(portal, "accounting_snapshot", return_value=snapshot):
                response = client.get("/apps/financeiro/api/accounting")
                self.assertEqual(expected, response.status_code)

    def test_endpoint_rejeita_usuario_sem_permissao(self):
        client = portal.app.test_client()
        with client.session_transaction() as session:
            session["usuario_id"] = USER["id"]
        with (
            mock.patch.object(portal, "ensure_database"),
            mock.patch.object(portal, "current_user_or_logout", return_value=USER),
            mock.patch.object(portal, "allowed_app_keys", return_value={"financeiro"}),
            mock.patch.object(portal, "app_visible_to_user", return_value=True),
            mock.patch.object(portal, "get_user_permissions", return_value={"financeiro": {"config"}}),
        ):
            response = client.get("/apps/financeiro/api/accounting")
        self.assertEqual(403, response.status_code)


if __name__ == "__main__":
    unittest.main()
