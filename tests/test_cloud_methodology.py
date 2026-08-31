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
    def test_render_runtime_forces_cloud_read_only_defaults(self):
        settings = portal.deployment_runtime_settings({"RENDER": "true"})

        self.assertEqual("cloud-readonly", settings["mode"])
        self.assertTrue(settings["readOnly"])
        self.assertEqual("alwaysdata", settings["cacheProvider"])

    def test_render_runtime_does_not_accept_local_mode_override(self):
        settings = portal.deployment_runtime_settings({
            "RENDER": "true",
            "NS_DEPLOY_MODE": "local",
            "NS_READ_ONLY": "0",
        })

        self.assertEqual("cloud-readonly", settings["mode"])
        self.assertTrue(settings["readOnly"])

    def test_nanotech_bootstrap_consumes_device_count_query(self):
        class FakeCursor:
            def __init__(self):
                self.pending = None

            def execute(self, statement, params=None):
                if self.pending is not None:
                    raise AssertionError("resultado anterior nao consumido")
                normalized = " ".join(statement.split()).upper()
                if normalized.startswith("SHOW COLUMNS"):
                    self.pending = [("existing_column",)]
                elif normalized == "SELECT COUNT(*) FROM TECNOLOGIA_DISPOSITIVOS":
                    self.pending = [(1,)]
                elif normalized.startswith("SELECT ID FROM USUARIOS"):
                    self.pending = [(1,)]

            def fetchone(self):
                row = self.pending[0] if self.pending else None
                self.pending = None
                return row

            def close(self):
                if self.pending is not None:
                    raise AssertionError("resultado pendente ao fechar cursor")

        class FakeConnection:
            def __init__(self, cursor):
                self._cursor = cursor

            def cursor(self):
                return self._cursor

            def commit(self):
                pass

            def close(self):
                pass

        server_cursor = FakeCursor()
        portal_cursor = FakeCursor()
        with (
            mock.patch.object(portal, "CLOUD_READ_ONLY", False),
            mock.patch.object(portal, "_db_ready", False),
            mock.patch.object(portal, "configured_client_id", return_value="nanotech"),
            mock.patch.object(portal, "get_server_conn", return_value=FakeConnection(server_cursor)),
            mock.patch.object(portal, "get_conn", return_value=FakeConnection(portal_cursor)),
            mock.patch.object(portal, "generate_password_hash", return_value="hash"),
        ):
            portal.ensure_database()
            self.assertTrue(portal._db_ready)

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

    def test_nanotech_contract_keeps_all_global_modules(self):
        payload = json.loads((PROJECT_DIR / "clientes-modulos.json").read_text(encoding="utf-8"))
        nanotech = next(item for item in payload["clients"] if item["id"] == "nanotech")

        self.assertTrue(nanotech["allModules"])
        external = {item["slug"]: item for item in nanotech["modules"]}
        self.assertEqual("externo", external["pacs"]["status"])
        self.assertEqual("LABORATORIO_PACS_URL", external["pacs"]["hrefEnv"])

    def test_contracts_keep_the_environment_module_boundaries(self):
        payload = json.loads((PROJECT_DIR / "clientes-modulos.json").read_text(encoding="utf-8"))
        clients = {item["id"]: item for item in payload["clients"]}

        self.assertEqual(
            {"nanostore"},
            {item["slug"] for item in clients["senhor"]["modules"]},
        )
        self.assertEqual(
            {"pacs"},
            {item["slug"] for item in clients["laboratorio"]["modules"]},
        )
        self.assertTrue(clients["nanotech"]["allModules"])
        self.assertTrue(
            {"pacs", "tatoo", "bpa", "gpsmusical"}.isdisjoint(
                {item["slug"] for item in clients["rio-branco"]["modules"]}
            )
        )

    def test_cloud_contract_includes_external_pacs(self):
        payload = json.loads((PROJECT_DIR / "clientes-modulos.json").read_text(encoding="utf-8"))
        cloud = next(item for item in payload["clients"] if item["id"] == "cloud")
        modules = {item["slug"]: item for item in cloud["modules"]}

        self.assertEqual("externo", modules["pacs"]["status"])
        self.assertEqual("LABORATORIO_PACS_URL", modules["pacs"]["hrefEnv"])

    def test_external_pacs_remains_visible_while_url_is_not_configured(self):
        cloud = next(
            item
            for item in portal.read_client_contracts()["clients"]
            if item["id"] == "cloud"
        )
        with (
            mock.patch.object(portal, "active_client_contract", return_value=cloud),
            mock.patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("LABORATORIO_PACS_URL", None)
            apps = {item["app_key"]: item for item in portal.active_external_apps()}

        self.assertEqual("/apps/pacs", apps["pacs"]["url"])
        self.assertIn("ainda nao configurada", apps["pacs"]["descricao"])

    def test_render_blueprint_is_read_only_and_uses_cloud_contract(self):
        blueprint = (PROJECT_DIR / "render.yaml").read_text(encoding="utf-8")

        self.assertIn("value: cloud", blueprint)
        self.assertIn("value: cloud-readonly", blueprint)
        self.assertIn("value: alwaysdata", blueprint)
        self.assertIn("- key: LABORATORIO_PACS_URL", blueprint)
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

    def test_accepts_alwaysdata_account_prefixed_cache_database(self):
        source = {"host": "db.local", "port": 3306, "database": "notechsoft"}
        target = {
            "host": "mysql-nanotechsoft.alwaysdata.net",
            "port": 3306,
            "database": "nanotechsoft_cache_riobranco",
        }

        cloud_cache_sync.validate_safety(source, target, ["chamados"])

    def test_rejects_administrative_cloud_database_as_snapshot_target(self):
        source = {"host": "db.local", "port": 3306, "database": "notechsoft"}
        target = {
            "host": "mysql-nanotechsoft.alwaysdata.net",
            "port": 3306,
            "database": "nanotechsoft_cloud",
        }
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CACHE_SYNC_ALLOW_ANY_TARGET", None)
            with self.assertRaises(ValueError):
                cloud_cache_sync.validate_safety(source, target, ["chamados"])


if __name__ == "__main__":
    unittest.main()
