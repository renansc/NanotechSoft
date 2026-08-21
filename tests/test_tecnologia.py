import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as portal
from apps.tecnologia import monitor


PROJECT_DIR = Path(__file__).resolve().parents[1]


class TecnologiaMonitorTests(unittest.TestCase):
    def test_normalize_device_payload(self):
        row = monitor.normalize_device_payload({
            "nome": "Servidor Windows",
            "tipo": "servidor",
            "host": "192.168.200.121",
            "porta": "445",
            "sonda": "icmp",
            "critico": True,
            "ativo": True,
            "latenciaAlertaMs": 12,
            "perdaAlertaPct": 3,
        })

        self.assertEqual("192.168.200.121", row["host"])
        self.assertEqual(445, row["porta"])
        self.assertEqual("SERVIDOR", row["tipo"])
        self.assertEqual(1, row["critico"])

    def test_normalize_rejects_invalid_host_and_tcp_without_port(self):
        base = {"nome": "Teste", "tipo": "OUTRO", "sonda": "ICMP"}
        with self.assertRaisesRegex(ValueError, "Host"):
            monitor.normalize_device_payload({**base, "host": "host com espaço"})
        with self.assertRaisesRegex(ValueError, "exige uma porta"):
            monitor.normalize_device_payload({**base, "host": "servidor.local", "sonda": "TCP"})

    def test_parse_ping_linux_output(self):
        result = monitor.parse_ping_output(
            "4 packets transmitted, 3 received, 25% packet loss\n"
            "rtt min/avg/max/mdev = 0.318/0.521/0.771/0.166 ms\n"
        )

        self.assertTrue(result["reachable"])
        self.assertEqual(25, result["packetLossPct"])
        self.assertEqual(0.52, result["latencyMs"])
        self.assertEqual(0.17, result["jitterMs"])

    def test_probe_combines_icmp_tcp_and_thresholds(self):
        device = {
            "host": "192.168.200.1", "porta": 80, "sonda": "ICMP", "tipo": "ROTEADOR",
            "latencia_alerta_ms": 10, "perda_alerta_pct": 2,
        }
        with (
            mock.patch.object(monitor, "ping_host", return_value={
                "reachable": True, "packetLossPct": 10, "latencyMs": 3, "jitterMs": 1,
            }),
            mock.patch.object(monitor, "tcp_host", return_value={"reachable": True, "latencyMs": 1}),
        ):
            result = monitor.probe_device(device)

        self.assertEqual("DEGRADADO", result["status"])
        self.assertTrue(result["serviceOk"])
        self.assertIn("perda 10%", result["message"])

    def test_tcp_can_confirm_online_when_icmp_is_blocked(self):
        device = {
            "host": "192.168.200.121", "porta": 445, "sonda": "TCP", "tipo": "SERVIDOR",
            "latencia_alerta_ms": 80, "perda_alerta_pct": 5,
        }
        with (
            mock.patch.object(monitor, "ping_host", return_value={
                "reachable": False, "packetLossPct": 100, "latencyMs": None, "jitterMs": None,
            }),
            mock.patch.object(monitor, "tcp_host", return_value={"reachable": True, "latencyMs": 2}),
        ):
            result = monitor.probe_device(device)

        self.assertEqual("DEGRADADO", result["status"])
        self.assertTrue(result["serviceOk"])

    def test_discovery_is_limited_to_private_24(self):
        with self.assertRaisesRegex(ValueError, "IPv4 privada"):
            monitor.discover_printers("8.8.8.0/24")
        with self.assertRaisesRegex(ValueError, "254 hosts"):
            monitor.discover_printers("192.168.0.0/16")

    def test_discovery_returns_only_hosts_with_printer_ports(self):
        def fake_ports(host, _timeout):
            return [9100, 515] if host.endswith(".2") else []

        with mock.patch.object(monitor, "_open_printer_ports", side_effect=fake_ports):
            result = monitor.discover_printers("192.168.50.0/30")

        self.assertEqual([{
            "host": "192.168.50.2", "ports": [9100, 515], "suggestedPort": 9100,
        }], result)

    def test_diagnosis_reports_offline_and_scope(self):
        diagnosis = monitor.build_network_diagnosis([
            {"ativo": True, "tipo": "INTERNET", "ultimaMetrica": {"status": "ONLINE"}},
            {"ativo": True, "tipo": "ROTEADOR", "ultimaMetrica": {"status": "OFFLINE"}},
        ])

        self.assertTrue(any(item["level"] == "critical" for item in diagnosis))
        self.assertTrue(any("Wi-Fi" in item["text"] for item in diagnosis))


class TecnologiaIntegrationTests(unittest.TestCase):
    def test_current_user_without_session_is_safe(self):
        with portal.app.test_request_context("/apps/tecnologia"):
            self.assertIsNone(portal.current_user_or_logout())

    def test_technology_api_without_session_returns_json_401(self):
        with (
            portal.app.test_request_context("/apps/tecnologia/api/overview"),
            mock.patch.object(portal, "current_user_or_logout", return_value=None),
        ):
            response, status = portal.enforce_app_permission()

        self.assertEqual(401, status)
        self.assertEqual("login necessário", response.get_json()["erro"])

    def test_manifest_and_allowed_app(self):
        manifest = json.loads((PROJECT_DIR / "apps/tecnologia/app.json").read_text(encoding="utf-8"))
        allowed = (PROJECT_DIR / "apps_liberados.txt").read_text(encoding="utf-8").splitlines()

        self.assertEqual("tecnologia", manifest["app_key"])
        self.assertEqual("apps/tecnologia/source", manifest["source_dir"])
        self.assertIn("tecnologia", allowed)
        self.assertIn("cadastros", manifest["menu_groups"])
        self.assertIn("relatorios", manifest["menu_groups"])

    def test_routes_are_registered(self):
        routes = {rule.rule: rule.methods for rule in portal.app.url_map.iter_rules()}

        self.assertIn("/apps/tecnologia", routes)
        self.assertIn("GET", routes["/apps/tecnologia/api/overview"])
        self.assertIn("POST", routes["/apps/tecnologia/api/probe"])
        self.assertIn("POST", routes["/apps/tecnologia/api/devices"])
        self.assertIn("DELETE", routes["/apps/tecnologia/api/devices/<int:device_id>"])

    def test_static_app_is_integrated(self):
        self.assertIn("tecnologia", portal.STATIC_APP_DIRS)
        self.assertEqual("Tecnologia", portal.STATIC_APP_NAMES["tecnologia"])
        html = (PROJECT_DIR / "apps/tecnologia/source/index.html").read_text(encoding="utf-8")
        javascript = (PROJECT_DIR / "apps/tecnologia/source/app.js").read_text(encoding="utf-8")

        self.assertIn("Monitoramento de Tecnologia", html)
        self.assertIn("Descobrir impressoras", html)
        self.assertIn('const API = "/apps/tecnologia/api"', javascript)

    def test_javascript_has_valid_syntax_in_chrome(self):
        browser = shutil.which("google-chrome")
        if not browser:
            self.skipTest("Google Chrome não instalado")
        javascript = (PROJECT_DIR / "apps/tecnologia/source/app.js").read_text(encoding="utf-8")
        page = (
            "<body><script>"
            f"try {{ new Function({json.dumps(javascript)}); document.body.textContent='ok'; }} "
            "catch (error) { document.body.textContent=error.name + ':' + error.message; }"
            "</script></body>"
        )
        with tempfile.TemporaryDirectory(prefix="tecnologia-js-") as temp_dir:
            page_path = Path(temp_dir) / "test.html"
            page_path.write_text(page, encoding="utf-8")
            result = subprocess.run(
                [browser, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--dump-dom", page_path.as_uri()],
                capture_output=True, text=True, timeout=30, check=True,
            )
        self.assertIn("<body>ok</body>", result.stdout)


if __name__ == "__main__":
    unittest.main()
