import json
import unittest
from pathlib import Path
from unittest import mock

import app as portal
from apps.impressoras.source import cups_service


ROOT = Path(__file__).resolve().parents[1]


class FakeConnection:
    def getPrinters(self):
        return {
            "Fila_A": {
                "printer-info": "Recepcao",
                "printer-make-and-model": "Modelo teste",
                "printer-state": 3,
                "printer-is-accepting-jobs": True,
                "job-hold-until-default": "indefinite",
            }
        }

    def getJobs(self, **_kwargs):
        return {
            17: {
                "job-name": "relatorio.pdf",
                "job-originating-user-name": "pessoa",
                "job-printer-uri": "ipp://cups/printers/Fila_A",
                "job-state": 4,
                "job-impressions": 3,
                "job-impressions-completed": 0,
                "copies": 2,
                "job-k-octets": 128,
                "time-at-creation": 1_700_000_000,
            }
        }


class PrinterModuleTests(unittest.TestCase):
    def test_manifest_catalogs_tasks_and_resources(self):
        manifest = json.loads((ROOT / "apps/impressoras/app.json").read_text(encoding="utf-8"))
        resources = {item["recurso"] for item in manifest["access_resources"]}
        self.assertEqual({"fila", "monitor", "historico", "gerenciar"}, resources)
        entries = portal.menu_access.entries(manifest, "rio-branco")
        self.assertEqual(4, len(entries))
        self.assertEqual(resources, {item["recurso"] for item in entries})

    def test_routes_and_schema_are_present(self):
        routes = {rule.rule for rule in portal.app.url_map.iter_rules()}
        self.assertIn("/apps/impressoras", routes)
        self.assertIn("/apps/impressoras/api/jobs", routes)
        self.assertIn("/apps/impressoras/api/jobs/release-all", routes)
        schema = (ROOT / "sql/schema.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS impressoras_trabalhos", schema)
        table_sql = schema[schema.index("CREATE TABLE IF NOT EXISTS impressoras_trabalhos"):].split(";", 1)[0]
        self.assertNotIn("senha", table_sql)

    def test_cups_adapter_normalizes_printers_jobs_and_page_counts(self):
        service = cups_service.CupsService()
        with mock.patch.object(service, "_connection", return_value=FakeConnection()):
            printers = service.printers()
            jobs = service.jobs()
        self.assertEqual("Recepcao", printers[0]["info"])
        self.assertTrue(printers[0]["secureDefault"])
        self.assertEqual("RETIDO", jobs[0]["state"])
        self.assertEqual(3, jobs[0]["requestedPages"])
        self.assertEqual(0, jobs[0]["printedPages"])
        self.assertEqual("pessoa", jobs[0]["cupsUser"])

    def test_api_permissions_are_server_side(self):
        user = {"id": 42, "login": "pessoa", "perfil": "usuario"}
        cases = [
            ("/apps/impressoras/api/overview", "GET", "monitor"),
            ("/apps/impressoras/api/jobs", "POST", "fila"),
            ("/apps/impressoras/api/jobs?scope=all", "GET", "historico"),
            ("/apps/impressoras/api/printers/Fila_A/pause", "POST", "gerenciar"),
        ]
        for path, method, resource in cases:
            for granted in (True, False):
                grants = {"impressoras": {resource if granted else "outro"}}
                with self.subTest(path=path, granted=granted), portal.app.test_request_context(path, method=method), \
                     mock.patch.object(portal, "allowed_app_keys", return_value={"impressoras"}), \
                     mock.patch.object(portal, "current_user_or_logout", return_value=user), \
                     mock.patch.object(portal, "get_user_permissions", return_value=grants):
                    result = portal.enforce_app_permission()
                    self.assertIsNone(result) if granted else self.assertEqual(403, result[1])


if __name__ == "__main__":
    unittest.main()
