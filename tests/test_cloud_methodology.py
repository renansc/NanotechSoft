import json
import os
import unittest
from pathlib import Path
from unittest import mock

import app as portal
from tools import cloud_cache_sync


PROJECT_DIR = Path(__file__).resolve().parents[1]


class CloudReadOnlyTests(unittest.TestCase):
    def test_cloud_blocks_business_writes(self):
        with (
            mock.patch.object(portal, "CLOUD_READ_ONLY", True),
            portal.app.test_request_context(
                "/apps/chamados/api/tickets",
                method="POST",
                json={"title": "nao gravar"},
            ),
        ):
            response, status = portal.enforce_cloud_read_only()

        self.assertEqual(403, status)
        self.assertEqual("cloud_read_only", response.get_json()["code"])

    def test_cloud_allows_login_session_but_not_user_changes(self):
        with mock.patch.object(portal, "CLOUD_READ_ONLY", True):
            with portal.app.test_request_context("/api/login", method="POST"):
                self.assertIsNone(portal.enforce_cloud_read_only())
            with portal.app.test_request_context("/api/usuarios/1", method="PUT"):
                _, status = portal.enforce_cloud_read_only()
                self.assertEqual(403, status)

    def test_cloud_never_bootstraps_or_migrates_database(self):
        with (
            mock.patch.object(portal, "CLOUD_READ_ONLY", True),
            mock.patch.object(portal, "_db_ready", False),
            mock.patch.object(portal.mysql.connector, "connect") as connect,
        ):
            portal.ensure_database()
        connect.assert_not_called()

    def test_technology_collector_does_not_start_in_cloud(self):
        with (
            mock.patch.object(portal, "CLOUD_READ_ONLY", True),
            mock.patch.object(portal.threading, "Thread") as thread,
        ):
            portal.start_technology_monitor()
        thread.assert_not_called()

    def test_cloud_selects_isolated_cache_database(self):
        with (
            mock.patch.object(portal, "CLOUD_READ_ONLY", True),
            mock.patch.object(
                portal,
                "CACHE_DATABASE_MAP",
                {"rio-branco": "cache_riobranco", "senhor": "cache_senhor"},
            ),
            mock.patch.object(portal.mysql.connector, "connect") as connect,
            portal.app.test_request_context("/"),
        ):
            portal.session["cache_client_id"] = "senhor"
            portal.get_conn()

        self.assertEqual("cache_senhor", connect.call_args.kwargs["database"])


class DeploymentProfileTests(unittest.TestCase):
    def test_profiles_cover_each_local_environment_and_render(self):
        payload = json.loads((PROJECT_DIR / "deploy/profiles.json").read_text(encoding="utf-8"))
        profiles = {item["id"]: item for item in payload["profiles"]}

        self.assertEqual(
            {"rio-branco", "nanotech", "laboratorio", "senhor", "render"},
            set(profiles),
        )
        self.assertEqual("cloud-readonly", profiles["render"]["mode"])
        self.assertFalse(profiles["render"]["localDatabase"])
        self.assertFalse(profiles["render"]["tailscale"])
        for profile_id in ("rio-branco", "nanotech", "laboratorio", "senhor"):
            self.assertEqual("local", profiles[profile_id]["mode"])
            self.assertTrue(profiles[profile_id]["tailscale"])

    def test_render_blueprint_is_read_only_and_uses_cloud_contract(self):
        blueprint = (PROJECT_DIR / "render.yaml").read_text(encoding="utf-8")

        self.assertIn("value: cloud", blueprint)
        self.assertIn("value: cloud-readonly", blueprint)
        self.assertIn("value: alwaysdata", blueprint)
        self.assertNotIn("- key: RIOB_BASE_URL", blueprint)

    def test_external_pacs_uses_environment_url_without_local_source(self):
        payload = json.loads((PROJECT_DIR / "clientes-modulos.json").read_text(encoding="utf-8"))
        laboratory = next(item for item in payload["clients"] if item["id"] == "laboratorio")
        pacs = laboratory["modules"][0]

        self.assertEqual("externo", pacs["status"])
        self.assertEqual("LABORATORIO_PACS_URL", pacs["hrefEnv"])
        self.assertFalse((PROJECT_DIR / "apps/pacs").exists())


class CloudCacheSyncSafetyTests(unittest.TestCase):
    def test_requires_explicit_table_allowlist(self):
        with self.assertRaises(ValueError):
            cloud_cache_sync.parse_tables("")

    def test_rejects_source_as_target(self):
        config = {
            "host": "db.local",
            "port": 3306,
            "database": "notechsoft",
        }
        with self.assertRaises(ValueError):
            cloud_cache_sync.validate_safety(config, dict(config), ["chamados"])

    def test_sensitive_tables_need_explicit_authorization(self):
        source = {"host": "db.local", "port": 3306, "database": "notechsoft"}
        target = {"host": "mysql.alwaysdata.net", "port": 3306, "database": "cache_riobranco"}
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CACHE_SYNC_ALLOW_SENSITIVE", None)
            with self.assertRaises(ValueError):
                cloud_cache_sync.validate_safety(source, target, ["usuarios"])


if __name__ == "__main__":
    unittest.main()
