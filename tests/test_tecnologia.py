import json
import shutil
import subprocess
import tempfile
import time
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

    def test_normalize_supports_snmp_and_prometheus(self):
        snmp = monitor.normalize_device_payload({
            "nome": "NVR", "tipo": "NVR", "host": "192.168.200.210", "sonda": "SNMP",
            "snmpCommunity": "rede-leitura", "snmpPort": 161,
        })
        exporter = monitor.normalize_device_payload({
            "nome": "Ubuntu", "tipo": "SERVIDOR", "host": "192.168.200.254", "sonda": "PROMETHEUS",
            "agentPort": 9100, "agentPath": "/metrics", "cpuAlertPct": 85,
        })

        self.assertEqual("rede-leitura", snmp["snmp_community"])
        self.assertEqual(9100, exporter["agente_porta"])
        self.assertEqual(85, exporter["cpu_alerta_pct"])

    def test_prometheus_parser_and_counter_rates(self):
        parsed = monitor._parse_prometheus(
            'node_cpu_seconds_total{cpu="0",mode="idle"} 10\n'
            'node_cpu_seconds_total{cpu="0",mode="user"} 5\n'
            'node_memory_MemTotal_bytes 1000\n'
        )
        rates = monitor._counter_rates(
            {"rxBytes": 2_000_000, "txBytes": 1_000_000},
            {"checkedEpoch": 10, "counters": {"rxBytes": 1_000_000, "txBytes": 500_000}},
            12,
        )

        self.assertEqual(2, len(parsed["node_cpu_seconds_total"]))
        self.assertEqual(4, rates["downloadMbps"])
        self.assertEqual(2, rates["uploadMbps"])

    def test_prometheus_collects_windows_inventory_for_device_card(self):
        body = (
            'windows_cpu_time_total{core="0",mode="idle"} 90\n'
            'windows_cpu_time_total{core="0",mode="user"} 10\n'
            'windows_memory_physical_total_bytes 1000\n'
            'windows_cpu_logical_processor 8\n'
            'windows_os_hostname{hostname="NOTEBOOK-RENAN",fqdn="NOTEBOOK-RENAN"} 1\n'
            'windows_memory_available_bytes 250\n'
            'windows_os_info{product="Microsoft Windows 11 Pro",version="10.0.26100",build_number="26100"} 1\n'
            'windows_system_boot_time_timestamp 6400\n'
            'windows_logical_disk_size_bytes{volume="C:"} 1000\n'
            'windows_logical_disk_free_bytes{volume="C:"} 200\n'
            'windows_net_bytes_received_total{nic="Wi-Fi"} 2000000\n'
            'windows_net_bytes_sent_total{nic="Wi-Fi"} 1000000\n'
        )
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = body.encode()
        device = {
            "host": "192.168.200.122", "agente_porta": 9182, "agente_path": "/metrics",
            "ultima_detalhes": json.dumps({"telemetry": {
                "checkedEpoch": 9990,
                "counters": {"cpuTotal": 80, "cpuIdle": 75, "rxBytes": 1000000, "txBytes": 500000},
            }}),
        }
        with (
            mock.patch.object(monitor.urllib.request, "urlopen", return_value=response),
            mock.patch.object(monitor.time, "time", return_value=10000),
        ):
            telemetry = monitor.collect_prometheus_metrics(device)

        self.assertEqual("NOTEBOOK-RENAN", telemetry["systemName"])
        self.assertEqual("Microsoft Windows 11 Pro", telemetry["osName"])
        self.assertEqual("26100", telemetry["osBuild"])
        self.assertEqual(8, telemetry["cpuCores"])
        self.assertEqual(75, telemetry["memoryPct"])
        self.assertEqual(1000, telemetry["memoryTotalBytes"])
        self.assertEqual(80, telemetry["diskPct"])
        self.assertEqual(3600, telemetry["uptimeSeconds"])
        self.assertEqual("C:", telemetry["disks"][0]["name"])
        self.assertIn("Wi-Fi", telemetry["interfaces"])

    def test_prometheus_server_endpoint_is_not_accepted_as_machine_exporter(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = (
            b"prometheus_build_info{version=\"3.0.0\"} 1\n"
            b"prometheus_engine_queries 0\n"
        )
        device = {"host": "192.168.200.184", "agente_porta": 9090, "agente_path": "/metrics"}

        with (
            mock.patch.object(monitor.urllib.request, "urlopen", return_value=response),
            self.assertRaisesRegex(RuntimeError, "servidor Prometheus"),
        ):
            monitor.collect_prometheus_metrics(device)

    def test_speed_measurement_uses_download_and_upload(self):
        with (
            mock.patch.object(monitor, "_http_download", return_value=1_000_000),
            mock.patch.object(monitor, "_http_upload", return_value=500_000),
        ):
            result = monitor.measure_internet_speed(download_bytes=4_000_000, upload_bytes=2_000_000, streams=4)

        self.assertEqual("OK", result["status"])
        self.assertGreater(result["downloadMbps"], 0)
        self.assertGreater(result["uploadMbps"], 0)

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

    def test_netbios_can_confirm_notebook_online_when_icmp_is_blocked(self):
        device = {
            "host": "192.168.200.122", "porta": None, "sonda": "ICMP", "tipo": "NOTEBOOK",
            "latencia_alerta_ms": 80, "perda_alerta_pct": 5,
        }
        with (
            mock.patch.object(monitor, "ping_host", return_value={
                "reachable": False, "packetLossPct": 100, "latencyMs": None, "jitterMs": None,
            }),
            mock.patch.object(monitor, "netbios_node_status", return_value={"ok": True, "name": "NOTEBOOK-RENAN"}),
        ):
            result = monitor.probe_device(device)

        self.assertEqual("DEGRADADO", result["status"])
        self.assertEqual("NOTEBOOK-RENAN", result["details"]["netbios"]["name"])

    def test_computer_identity_classifies_windows_and_linux(self):
        ping_result = mock.Mock(returncode=0, stdout="64 bytes ttl=128", stderr="")
        with (
            mock.patch.object(monitor.subprocess, "run", return_value=ping_result),
            mock.patch.object(monitor, "netbios_node_status", return_value={"ok": True, "name": "PC-03"}),
            mock.patch.object(monitor, "tcp_host", side_effect=lambda _host, port, timeout_seconds: {"reachable": port == 445}),
        ):
            result = monitor._computer_identity("192.168.200.136", 0.1)

        self.assertEqual("Windows", result["osFamily"])
        self.assertEqual("COMPUTADOR", result["suggestedType"])
        self.assertIn(445, result["ports"])

    def test_computer_identity_ignores_router_with_windows_sharing_ports(self):
        ping_result = mock.Mock(returncode=0, stdout="64 bytes ttl=64", stderr="")
        with (
            mock.patch.object(monitor.subprocess, "run", return_value=ping_result),
            mock.patch.object(monitor, "netbios_node_status", return_value={"ok": True, "name": "RT-AC68U-E680"}),
            mock.patch.object(monitor, "tcp_host", return_value={"reachable": True}),
        ):
            result = monitor._computer_identity("192.168.200.138", 0.1)

        self.assertIsNone(result)

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

    def test_diagnosis_reports_low_speed_and_resource_bottleneck(self):
        diagnosis = monitor.build_network_diagnosis([{
            "ativo": True, "nome": "Servidor", "tipo": "SERVIDOR",
            "cpuAlertPct": 80, "memoryAlertPct": 90, "diskAlertPct": 90, "trafficAlertMbps": 100,
            "ultimaMetrica": {"status": "DEGRADADO", "telemetry": {"cpuPct": 95}},
        }], {
            "status": "DEGRADADO", "downloadMbps": 20, "uploadMbps": 15,
            "downloadAlertMbps": 50, "uploadAlertMbps": 10,
        })

        self.assertTrue(any("Download baixo" in item["text"] for item in diagnosis))
        self.assertTrue(any("CPU em 95%" in item["text"] for item in diagnosis))


class TecnologiaIntegrationTests(unittest.TestCase):
    def test_technology_alert_email_requires_password_when_user_is_configured(self):
        environment = {
            "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587",
            "SMTP_USER": "monitor@example.test", "SMTP_PASSWORD": "",
            "SMTP_FROM": "monitor@example.test",
            "TECH_ALERT_EMAIL_TO": "solucoestecnologicasrenan@gmail.com",
        }
        with mock.patch.dict(portal.os.environ, environment, clear=False):
            config = portal.technology_email_config()

        self.assertFalse(config["configured"])

    def test_technology_alert_email_uses_configured_smtp(self):
        client = mock.MagicMock()
        client.__enter__.return_value = client
        environment = {
            "SMTP_HOST": "smtp.example.test", "SMTP_PORT": "587",
            "SMTP_USER": "monitor@example.test", "SMTP_PASSWORD": "secret",
            "SMTP_FROM": "monitor@example.test", "SMTP_USE_TLS": "1",
            "TECH_ALERT_EMAIL_TO": "solucoestecnologicasrenan@gmail.com",
        }
        with (
            mock.patch.dict(portal.os.environ, environment, clear=False),
            mock.patch.object(portal.smtplib, "SMTP", return_value=client) as smtp,
        ):
            recipient = portal.send_technology_email("Teste", "Mensagem")

        self.assertEqual("solucoestecnologicasrenan@gmail.com", recipient)
        smtp.assert_called_once_with("smtp.example.test", 587, timeout=15)
        client.starttls.assert_called_once()
        client.login.assert_called_once_with("monitor@example.test", "secret")
        message = client.send_message.call_args.args[0]
        self.assertEqual("Teste", message["Subject"])
        self.assertEqual("solucoestecnologicasrenan@gmail.com", message["To"])

    def test_technology_alert_email_body_lists_resource_and_limit(self):
        body = portal.technology_alert_email_body([{
            "type": "ALERTA", "deviceName": "Notebook Renan", "host": "192.168.200.122",
            "label": "memória RAM", "value": 91.2, "limit": 90,
        }], now=portal.dt.datetime(2026, 8, 21, 10, 30))

        self.assertIn("Notebook Renan (192.168.200.122)", body)
        self.assertIn("memória RAM em 91.2%", body)
        self.assertIn("limite 90.0%", body)

    def test_technology_resource_alert_transitions_have_cooldown_and_recovery_margin(self):
        now = portal.dt.datetime(2026, 8, 21, 10, 30)
        retry = portal.dt.timedelta(minutes=15)
        reminder = portal.dt.timedelta(hours=6)

        self.assertEqual("ALERTA", portal.technology_resource_alert_action(
            None, 90, 90, now, retry, reminder, 5,
        ))
        self.assertIsNone(portal.technology_resource_alert_action(
            {"ativo": 1, "ultimo_email_em": None, "ultima_tentativa_em": now - portal.dt.timedelta(minutes=5)},
            93, 90, now, retry, reminder, 5,
        ))
        self.assertEqual("LEMBRETE", portal.technology_resource_alert_action(
            {"ativo": 1, "ultimo_email_em": now - portal.dt.timedelta(hours=7)},
            91, 90, now, retry, reminder, 5,
        ))
        self.assertIsNone(portal.technology_resource_alert_action(
            {"ativo": 1, "ultimo_email_em": now}, 87, 90, now, retry, reminder, 5,
        ))
        self.assertEqual("RECUPERADO", portal.technology_resource_alert_action(
            {"ativo": 1, "ultimo_email_em": now}, 85, 90, now, retry, reminder, 5,
        ))

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
        self.assertIn("POST", routes["/apps/tecnologia/api/alerts/test-email"])
        self.assertIn("POST", routes["/apps/tecnologia/api/speed-test"])
        self.assertIn("GET", routes["/apps/tecnologia/api/speed-history"])
        self.assertIn("POST", routes["/apps/tecnologia/api/discover-computers"])
        self.assertIn("POST", routes["/apps/tecnologia/api/devices"])
        self.assertIn("DELETE", routes["/apps/tecnologia/api/devices/<int:device_id>"])

    def test_static_app_is_integrated(self):
        self.assertIn("tecnologia", portal.STATIC_APP_DIRS)
        self.assertEqual("Tecnologia", portal.STATIC_APP_NAMES["tecnologia"])
        html = (PROJECT_DIR / "apps/tecnologia/source/index.html").read_text(encoding="utf-8")
        javascript = (PROJECT_DIR / "apps/tecnologia/source/app.js").read_text(encoding="utf-8")

        self.assertIn("Monitoramento de Tecnologia", html)
        self.assertIn("Descobrir impressoras", html)
        self.assertIn("Agentes e protocolos", html)
        self.assertIn("RELOGIO_PONTO", html)
        self.assertIn("Prometheus exporter", html)
        self.assertIn("Descobrir computadores", html)
        self.assertIn("deviceDetailsModal", html)
        self.assertIn("Atualizar agora", html)
        self.assertIn("Alertas por e-mail", html)
        self.assertIn("Enviar e-mail de teste", html)
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
