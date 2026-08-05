import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_DIR))

from nanostore.routes import _cert_path, _https_runtime_config


class HttpsRuntimeTest(unittest.TestCase):
    def test_public_url_contributes_only_its_hostname(self):
        env = {
            "CERT_APP_HOSTS": "192.168.200.10",
            "PUBLIC_BASE_URL": "https://192.168.200.254/apps/nanostore",
        }
        with patch.dict(os.environ, env, clear=False):
            runtime = _https_runtime_config()
        self.assertIn("192.168.200.254", runtime["cert_hosts"])
        self.assertNotIn(env["PUBLIC_BASE_URL"], runtime["cert_hosts"])

    def test_certificate_paths_can_be_shared_with_portal_proxy(self):
        expected = "/app/apps/riob/source/certs/riobranco-ca.crt"
        with patch.dict(os.environ, {"APP_CA_CERT_PATH": expected}, clear=False):
            self.assertEqual(_cert_path("nanostore-ca.crt"), expected)


if __name__ == "__main__":
    unittest.main()
