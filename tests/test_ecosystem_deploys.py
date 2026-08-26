import json
import unittest
from pathlib import Path
from unittest import mock

import app as portal


PROJECT_DIR = Path(__file__).resolve().parents[1]


class EcosystemDeployTests(unittest.TestCase):
    def test_ecosystem_references_the_primary_pacs_and_protects_nanotech_catalog(self):
        ecosystem = json.loads((PROJECT_DIR / "deploy/ecosystem.json").read_text(encoding="utf-8"))
        deployments = {item["id"]: item for item in ecosystem["deployments"]}
        manifests = {
            json.loads(path.read_text(encoding="utf-8"))["app_key"]
            for path in (PROJECT_DIR / "apps").glob("*/app.json")
        }

        self.assertEqual("git@github.com:renansc/RisPacsFull.git", ecosystem["components"]["pacs"]["repository"])
        self.assertEqual("main", ecosystem["components"]["pacs"]["branch"])
        self.assertTrue(deployments["nanotech"]["allModules"])
        self.assertTrue(set(deployments["nanotech"]["requiredModules"]) - {"pacs"} <= manifests)
        self.assertEqual(["pacs"], deployments["laboratorio"]["requiredModules"])
        self.assertEqual("pacs", deployments["laboratorio"]["component"])

    def test_senhor_update_window_starts_after_18h(self):
        ecosystem = json.loads((PROJECT_DIR / "deploy/ecosystem.json").read_text(encoding="utf-8"))
        senhor = next(item for item in ecosystem["deployments"] if item["id"] == "senhor")

        self.assertEqual("America/Sao_Paulo", senhor["updateWindow"]["timezone"])
        self.assertEqual("18:00", senhor["updateWindow"]["start"])
        self.assertEqual(["nanostore"], senhor["requiredModules"])

    def test_riob_deploy_rejects_empty_local_directory_when_cifs_is_missing(self):
        common = (PROJECT_DIR / "deploy/lib/common.sh").read_text(encoding="utf-8")

        self.assertIn('source_fstype="$(findmnt -rn -T "$source" -o FSTYPE', common)
        self.assertIn('source_fstype" != "cifs"', common)
        self.assertTrue((PROJECT_DIR / "deploy/systemd/media-serverwin.mount.d/retry.conf").is_file())
        self.assertTrue((PROJECT_DIR / "deploy/systemd/media-serverwin.automount.d/retry.conf").is_file())
        compose = (PROJECT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("TZ: ${TZ:-America/Sao_Paulo}", compose)

    def test_server_blocks_module_outside_deploy_even_for_admin(self):
        with (
            portal.app.test_request_context("/apps/bpa"),
            mock.patch.object(portal, "allowed_app_keys", return_value={"nanostore"}),
            mock.patch.object(portal, "current_user_or_logout") as current_user,
        ):
            response, status = portal.enforce_app_permission()

        self.assertEqual(404, status)
        self.assertEqual("app nao habilitado neste deploy", response.get_json()["erro"])
        current_user.assert_not_called()

    def test_nanotech_all_modules_policy_allows_global_app_for_admin(self):
        admin = {"id": 1, "perfil": "admin", "ativo": 1}
        with (
            portal.app.test_request_context("/apps/bpa"),
            mock.patch.object(portal, "allowed_app_keys", return_value=None),
            mock.patch.object(portal, "current_user_or_logout", return_value=admin),
        ):
            self.assertIsNone(portal.enforce_app_permission())

    def test_restored_global_static_routes_are_registered(self):
        routes = {rule.rule: rule.methods for rule in portal.app.url_map.iter_rules()}

        for app_key in ("gpsmusical", "bpa", "tatoo"):
            with self.subTest(app_key=app_key):
                self.assertIn(app_key, portal.STATIC_APP_DIRS)
                self.assertIn(f"/apps/{app_key}", routes)
                self.assertIn(f"/apps/{app_key}/original", routes)


if __name__ == "__main__":
    unittest.main()
