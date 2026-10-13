import json
import unittest
from pathlib import Path
from unittest import mock

import app as portal
from apps.impressoras.source import cups_service


ROOT = Path(__file__).resolve().parents[1]


class FakeConnection:
    def __init__(self):
        self.defaults = []

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

    def getPrinterAttributes(self, name, requested_attributes=None):
        del name, requested_attributes
        return {
            "job-hold-until-default": "indefinite",
            "printer-state-reasons": ["hold-new-jobs"],
        }

    def addPrinterOptionDefault(self, name, option, value):
        self.defaults.append((name, option, value))

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
        self.assertIn("/apps/impressoras/api/user-links", routes)
        self.assertIn("/apps/impressoras/api/user-links/<int:link_id>", routes)
        schema = (ROOT / "sql/schema.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS impressoras_trabalhos", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS impressoras_vinculos_usuario", schema)
        table_sql = schema[schema.index("CREATE TABLE IF NOT EXISTS impressoras_trabalhos"):].split(";", 1)[0]
        self.assertNotIn("senha", table_sql)

    def test_cups_adapter_normalizes_printers_jobs_and_page_counts(self):
        service = cups_service.CupsService()
        with mock.patch.object(service, "_connection", return_value=FakeConnection()):
            printers = service.printers()
            jobs = service.jobs()
        self.assertEqual("Recepcao", printers[0]["info"])
        self.assertTrue(printers[0]["secureDefault"])
        self.assertTrue(printers[0]["holdingNewJobs"])
        self.assertEqual("RETIDO", jobs[0]["state"])
        self.assertEqual(3, jobs[0]["requestedPages"])
        self.assertEqual(0, jobs[0]["printedPages"])
        self.assertEqual("pessoa", jobs[0]["cupsUser"])

    def test_lpstat_recovers_owner_hidden_by_ipp_privacy(self):
        service = cups_service.CupsService()
        connection = FakeConnection()
        jobs = connection.getJobs()
        jobs[17].pop("job-originating-user-name")
        connection.getJobs = mock.Mock(return_value=jobs)
        completed = mock.Mock(
            returncode=0,
            stdout="Fila_A-17   usuario-do-pc   131072   Tue Oct 13 14:50:57 2026\n",
            stderr="",
        )
        with mock.patch.object(service, "_connection", return_value=connection), \
             mock.patch.object(cups_service.subprocess, "run", return_value=completed) as run:
            normalized = service.jobs()
        self.assertEqual("usuario-do-pc", normalized[0]["cupsUser"])
        self.assertEqual(["lpstat", "-W", "all", "-o"], run.call_args.args[0])

    def test_guard_sets_and_verifies_secure_queue_default(self):
        service = cups_service.CupsService()
        connection = FakeConnection()
        connection.getPrinterAttributes = mock.Mock(side_effect=[
            {
                "job-hold-until-default": "no-hold",
                "printer-state-reasons": ["none"],
            },
            {
                "job-hold-until-default": "indefinite",
                "printer-state-reasons": ["hold-new-jobs"],
            },
        ])
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(service, "_connection", return_value=connection), \
             mock.patch.object(cups_service.subprocess, "run", return_value=completed) as run:
            result = service.enforce_secure_queues()
        self.assertEqual([("Fila_A", "job-hold-until", "indefinite")], connection.defaults)
        run.assert_called_once()
        self.assertIn("--hold", run.call_args.args[0])
        self.assertEqual(2, connection.getPrinterAttributes.call_count)
        self.assertEqual([{"name": "Fila_A", "secure": True}], result)

    def test_compose_runs_continuous_cups_guard(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("cups-guard:", compose)
        self.assertIn('apps.impressoras.source.cups_service", "--watch"', compose)
        self.assertIn('CUPS_GUARD_SERVICE="cups-guard"', (ROOT / "deploy/lib/common.sh").read_text(encoding="utf-8"))

    def test_user_mapping_ui_reuses_manage_permission(self):
        page = (ROOT / "apps/impressoras/source/index.html").read_text(encoding="utf-8")
        script = (ROOT / "apps/impressoras/source/app.js").read_text(encoding="utf-8")
        backend = (ROOT / "apps/impressoras/source/backend.py").read_text(encoding="utf-8")
        self.assertIn('id="userLinkForm"', page)
        self.assertIn('/user-links', script)
        self.assertIn('require("gerenciar")', backend)

    def test_api_permissions_are_server_side(self):
        user = {"id": 42, "login": "pessoa", "perfil": "usuario"}
        cases = [
            ("/apps/impressoras/api/overview", "GET", "monitor"),
            ("/apps/impressoras/api/jobs", "POST", "fila"),
            ("/apps/impressoras/api/jobs?scope=all", "GET", "historico"),
            ("/apps/impressoras/api/user-links", "GET", "gerenciar"),
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
