import json
import unittest
from pathlib import Path
from unittest import mock

import app as portal


class CommunicationAccessTests(unittest.TestCase):
    def test_popup_does_not_expand_api_permissions(self):
        cases = [
            ("chat/mensagens", "POST", {"chat"}, True),
            ("chat/mensagens", "POST", {"vendas"}, False),
            ("sip/me", "GET", {"chat"}, False),
            ("sip/me", "GET", {"config"}, True),
            ("sip/config", "PUT", {"chat"}, False),
            ("sip/config", "PUT", {"config"}, True),
            ("agent/chat", "POST", {"vendas"}, True),
            ("agent/chat", "POST", set(), False),
        ]
        for route, method, resources, allowed in cases:
            with self.subTest(route=route, resources=resources), portal.app.test_request_context(
                "/apps/riob/api/" + route, method=method
            ), mock.patch.object(portal, "current_user_or_logout", return_value={"id": 42, "perfil": "usuario"}), mock.patch.object(
                portal, "allowed_app_keys", return_value={"riob"}
            ), mock.patch.object(portal, "get_user_permissions", return_value={"riob": resources}):
                result = portal.enforce_app_permission()
                if allowed:
                    self.assertIsNone(result)
                else:
                    self.assertEqual(403, result[1])

    def test_alias_catalog_preserves_existing_full_access(self):
        manifests = [json.loads((Path(portal.BASE_DIR) / "apps" / key / "app.json").read_text())
                     for key in ("riob-chat", "riob-chat-ia", "riob-telefonia")]
        with mock.patch.object(portal, "list_apps", return_value=manifests):
            permissions = {item["app_key"]: ["*"] for item in manifests}
            self.assertEqual(permissions, portal.validate_user_permissions(permissions))
            for item in portal.permission_catalog():
                self.assertEqual(["*"], [resource["key"] for resource in item["recursos"]])


if __name__ == "__main__":
    unittest.main()
