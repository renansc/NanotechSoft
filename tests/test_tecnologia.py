import json
import datetime as dt
import shutil
import smtplib
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
            "networkAddresses": [
                {"label": "Wi-Fi", "host": "192.168.200.122"},
                {"label": "Tailscale", "host": "100.80.20.10"},
            ],
        })

        self.assertEqual("192.168.200.121", row["host"])
        self.assertEqual(445, row["porta"])
        self.assertEqual("SERVIDOR", row["tipo"])
        self.assertEqual(1, row["critico"])
        self.assertEqual([
            {"label": "Wi-Fi", "host": "192.168.200.122"},
            {"label": "Tailscale", "host": "100.80.20.10"},
        ], json.loads(row["enderecos_adicionais"]))

    def test_normalize_rejects_invalid_host_and_tcp_without_port(self):
        base = {"nome": "Teste", "tipo": "OUTRO", "sonda": "ICMP"}
        with self.assertRaisesRegex(ValueError, "Host"):
            monitor.normalize_device_payload({**base, "host": "host com espaço"})
        with self.assertRaisesRegex(ValueError, "exige uma porta"):
            monitor.normalize_device_payload({**base, "host": "servidor.local", "sonda": "TCP"})
        with self.assertRaisesRegex(ValueError, "Host"):
            monitor.normalize_device_payload({
                **base, "host": "192.168.200.10",
                "networkAddresses": [{"label": "Wi-Fi", "host": "IP inválido"}],
            })

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

    def test_snmp_collects_printer_mib_inventory_and_supplies(self):
        rows_by_oid = {
            ".1.3.6.1.2.1.1": [
                (".1.3.6.1.2.1.1.1.0", "HP Laser 408dn"),
                (".1.3.6.1.2.1.1.3.0", "(864000) 2:24:00.00"),
                (".1.3.6.1.2.1.1.5.0", "HP-TESTE"),
            ],
            ".1.3.6.1.2.1.31.1.1.1.1": [(".1.3.6.1.2.1.31.1.1.1.1.1", "eth0")],
            ".1.3.6.1.2.1.31.1.1.1.6": [(".1.3.6.1.2.1.31.1.1.1.6.1", "1000000")],
            ".1.3.6.1.2.1.31.1.1.1.10": [(".1.3.6.1.2.1.31.1.1.1.10.1", "500000")],
            ".1.3.6.1.2.1.31.1.1.1.15": [(".1.3.6.1.2.1.31.1.1.1.15.1", "1000")],
            ".1.3.6.1.2.1.25.3.3.1.2": [],
            ".1.3.6.1.2.1.25.3.5.1.1": [(".1.3.6.1.2.1.25.3.5.1.1.1", "idle(3)")],
            ".1.3.6.1.2.1.43.5.1.1.17": [(".1.3.6.1.2.1.43.5.1.1.17.1", "SERIAL-123")],
            ".1.3.6.1.2.1.43.10.2.1.4": [(".1.3.6.1.2.1.43.10.2.1.4.1.1", "125571")],
            ".1.3.6.1.2.1.43.11.1.1.6": [
                (".1.3.6.1.2.1.43.11.1.1.6.1.1", "Toner preto"),
                (".1.3.6.1.2.1.43.11.1.1.6.1.2", "Fusor"),
            ],
            ".1.3.6.1.2.1.43.11.1.1.8": [
                (".1.3.6.1.2.1.43.11.1.1.8.1.1", "15000"),
                (".1.3.6.1.2.1.43.11.1.1.8.1.2", "90000"),
            ],
            ".1.3.6.1.2.1.43.11.1.1.9": [
                (".1.3.6.1.2.1.43.11.1.1.9.1.1", "7500"),
                (".1.3.6.1.2.1.43.11.1.1.9.1.2", "-3"),
            ],
        }

        with (
            mock.patch.object(monitor, "_snmp_walk", side_effect=lambda host, community, port, oid: rows_by_oid[oid]),
            mock.patch.object(monitor.time, "time", return_value=10000),
        ):
            telemetry = monitor.collect_snmp_metrics({
                "host": "192.168.200.147", "tipo": "IMPRESSORA",
                "snmp_community": "somente-leitura", "snmp_port": 161,
            })

        self.assertEqual("SNMPv2c", telemetry["protocol"])
        self.assertEqual("Ociosa", telemetry["printerStatus"])
        self.assertEqual("SERIAL-123", telemetry["serialNumber"])
        self.assertEqual(125571, telemetry["pageCount"])
        self.assertEqual(8640, telemetry["uptimeSeconds"])
        self.assertEqual(["eth0"], telemetry["interfaces"])
        self.assertEqual(50, telemetry["supplies"][0]["pct"])
        self.assertEqual("Disponível", telemetry["supplies"][1]["status"])

    def test_snmp_nvr_falls_back_to_if_table_and_reads_enterprise_inventory(self):
        rows_by_oid = {
            ".1.3.6.1.2.1.1": [
                (".1.3.6.1.2.1.1.1.0", "none"),
                (".1.3.6.1.2.1.1.2.0", ".1.3.6.1.4.1.1004849.3.2.10"),
                (".1.3.6.1.2.1.1.3.0", "(172000) 0:28:40.00"),
                (".1.3.6.1.2.1.1.5.0", "(none)"),
            ],
            ".1.3.6.1.2.1.31.1.1.1.1": [],
            ".1.3.6.1.2.1.31.1.1.1.6": [],
            ".1.3.6.1.2.1.31.1.1.1.10": [],
            ".1.3.6.1.2.1.31.1.1.1.15": [],
            ".1.3.6.1.2.1.2.2.1.2": [
                (".1.3.6.1.2.1.2.2.1.2.1", "lo"),
                (".1.3.6.1.2.1.2.2.1.2.3", "eth0"),
            ],
            ".1.3.6.1.2.1.2.2.1.10": [
                (".1.3.6.1.2.1.2.2.1.10.1", "100"),
                (".1.3.6.1.2.1.2.2.1.10.3", "3000000"),
            ],
            ".1.3.6.1.2.1.2.2.1.16": [
                (".1.3.6.1.2.1.2.2.1.16.1", "100"),
                (".1.3.6.1.2.1.2.2.1.16.3", "1500000"),
            ],
            ".1.3.6.1.2.1.2.2.1.5": [
                (".1.3.6.1.2.1.2.2.1.5.1", "10000000"),
                (".1.3.6.1.2.1.2.2.1.5.3", "1000000000"),
            ],
            ".1.3.6.1.2.1.25.3.3.1.2": [],
            ".1.3.6.1.4.1.1004849.2.1.1": [
                (".1.3.6.1.4.1.1004849.2.1.1.1.0", "4.000.00IB003.0"),
            ],
            ".1.3.6.1.4.1.1004849.2.1.2": [
                (".1.3.6.1.4.1.1004849.2.1.2.4.0", "SERIAL-NVR"),
                (".1.3.6.1.4.1.1004849.2.1.2.5.0", "4.0.0003.0"),
                (".1.3.6.1.4.1.1004849.2.1.2.6.0", "MHDX 3116"),
                (".1.3.6.1.4.1.1004849.2.1.2.7.0", "HDCVI"),
                (".1.3.6.1.4.1.1004849.2.1.2.9.0", "MHDX"),
            ],
            ".1.3.6.1.4.1.1004849.2.1.10": [
                (".1.3.6.1.4.1.1004849.2.1.10.1.0", "Linux"),
                (".1.3.6.1.4.1.1004849.2.1.10.2.0", "3.18.20"),
            ],
            ".1.3.6.1.4.1.1004849.2.10.2.1": [
                (".1.3.6.1.4.1.1004849.2.10.2.1.0", "16"),
            ],
        }
        previous = {"telemetry": {
            "checkedEpoch": 9990,
            "counters": {"source": "ifTable32", "rxBytes": 2000000, "txBytes": 1000000},
        }}
        with (
            mock.patch.object(monitor, "_snmp_walk", side_effect=lambda host, community, port, oid: rows_by_oid[oid]),
            mock.patch.object(monitor.time, "time", return_value=10000),
        ):
            telemetry = monitor.collect_snmp_metrics({
                "host": "192.168.200.210", "tipo": "NVR",
                "snmp_community": "somente-leitura", "snmp_port": 161,
                "ultima_detalhes": json.dumps(previous),
            })

        self.assertEqual("MHDX 3116", telemetry["model"])
        self.assertEqual("SERIAL-NVR", telemetry["serialNumber"])
        self.assertEqual("Linux", telemetry["osName"])
        self.assertEqual(16, telemetry["channelCapacity"])
        self.assertEqual(["lo", "eth0"], telemetry["interfaces"])
        self.assertEqual(1000, telemetry["networkCapacityMbps"])
        self.assertEqual(0.8, telemetry["downloadMbps"])
        self.assertEqual(0.4, telemetry["uploadMbps"])
        self.assertEqual("", telemetry["systemName"])

    def test_snmp_walk_ignores_unsupported_oid_as_data(self):
        result = mock.Mock(
            returncode=0,
            stdout=".1.3.6.1.2.1.31 = No Such Object available on this agent at this OID\n",
        )
        with mock.patch.object(monitor.subprocess, "run", return_value=result):
            self.assertEqual([], monitor._snmp_walk("192.168.200.210", "read-only", 161, ".1.3.6.1.2.1.31"))

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
            'windows_net_current_bandwidth_bytes{nic="Wi-Fi"} 1000000\n'
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
        self.assertEqual(8, telemetry["networkCapacityMbps"])
        self.assertEqual(10, telemetry["networkPct"])
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

    def test_probe_uses_alternate_address_for_prometheus_exporter(self):
        device = {
            "host": "192.168.200.122",
            "enderecos_adicionais": json.dumps([
                {"label": "Cabo", "host": "192.168.200.123"},
                {"label": "Tailscale", "host": "100.80.20.10"},
            ]),
            "porta": None, "sonda": "PROMETHEUS", "tipo": "NOTEBOOK",
            "agente_porta": 9182, "agente_path": "/metrics",
            "latencia_alerta_ms": 80, "perda_alerta_pct": 5,
        }

        def fake_ping(host):
            reachable = host == "192.168.200.123"
            return {
                "reachable": reachable,
                "packetLossPct": 0 if reachable else 100,
                "latencyMs": 2 if reachable else None,
                "jitterMs": 0.2 if reachable else None,
            }

        with (
            mock.patch.object(monitor, "ping_host", side_effect=fake_ping),
            mock.patch.object(monitor, "tcp_host", side_effect=lambda host, _port: {
                "reachable": host == "192.168.200.123", "latencyMs": 1,
            }),
            mock.patch.object(monitor, "netbios_node_status", return_value={"ok": False, "name": ""}),
            mock.patch.object(monitor, "collect_prometheus_metrics", return_value={
                "cpuPct": 20, "memoryPct": 30, "diskPct": 40,
            }) as collect,
        ):
            result = monitor.probe_device(device)

        self.assertEqual("ONLINE", result["status"])
        self.assertEqual("192.168.200.123", result["details"]["activeAddress"])
        self.assertIn("via Cabo", result["message"])
        self.assertTrue(result["details"]["addresses"][1]["active"])
        self.assertEqual("192.168.200.123", collect.call_args.args[0]["host"])

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

    def test_printer_scan_excludes_node_exporter_on_port_9100(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = (
            b'node_exporter_build_info{version="1.10.2"} 1\n'
            b'node_cpu_seconds_total{cpu="0",mode="idle"} 10\n'
        )
        with (
            mock.patch.object(monitor, "tcp_host", side_effect=lambda _host, port, timeout_seconds: {
                "reachable": port == 9100,
            }),
            mock.patch.object(monitor.urllib.request, "urlopen", return_value=response),
        ):
            ports = monitor._open_printer_ports("192.168.200.184", 0.15)

        self.assertEqual([], ports)

    def test_printer_scan_keeps_raw_print_service_on_port_9100(self):
        with (
            mock.patch.object(monitor, "tcp_host", side_effect=lambda _host, port, timeout_seconds: {
                "reachable": port == 9100,
            }),
            mock.patch.object(
                monitor.urllib.request,
                "urlopen",
                side_effect=monitor.urllib.error.URLError("não é HTTP"),
            ),
        ):
            ports = monitor._open_printer_ports("192.168.200.138", 0.15)

        self.assertEqual([9100], ports)

    def test_diagnosis_reports_offline_and_scope(self):
        diagnosis = monitor.build_network_diagnosis([
            {"id": 1, "ativo": True, "tipo": "INTERNET", "ultimaMetrica": {"status": "ONLINE"}},
            {"id": 2, "ativo": True, "tipo": "ROTEADOR", "host": "192.168.200.1", "ultimaMetrica": {"status": "OFFLINE", "message": "sem resposta"}},
        ])

        self.assertTrue(any(item["level"] == "critical" for item in diagnosis))
        self.assertTrue(any("Wi-Fi" in item["text"] for item in diagnosis))

    def test_diagnosis_explains_gateway_degradation_and_links_history(self):
        diagnosis = monitor.build_network_diagnosis([
            {"id": 1, "ativo": True, "tipo": "INTERNET", "ultimaMetrica": {"status": "ONLINE"}},
            {
                "id": 2, "ativo": True, "tipo": "ROTEADOR", "host": "192.168.200.1",
                "ultimaMetrica": {
                    "status": "DEGRADADO", "message": "perda 25%",
                    "checkedAt": "2026-08-22T10:20:41.551Z",
                },
            },
        ])

        gateway = next(item for item in diagnosis if item.get("deviceId") == 2)
        self.assertEqual("warning", gateway["level"])
        self.assertIn("perda 25%", gateway["text"])
        self.assertIn("envia e-mail", gateway["detail"])
        self.assertEqual("2026-08-22T10:20:41.551Z", gateway["checkedAt"])

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
    def test_registered_device_hosts_include_additional_interfaces(self):
        rows = [{
            "id": 13,
            "nome": "Notebook Renan",
            "host": "192.168.200.10",
            "enderecos_adicionais": json.dumps([
                {"label": "Wi-Fi", "host": "192.168.200.122"},
                {"label": "Tailscale", "host": "100.66.72.69"},
            ]),
            "ultima_detalhes": json.dumps({
                "telemetry": {"systemName": "Renan-Note"},
                "netbios": {"name": "RENAN-NOTE"},
            }),
        }, {
            "id": 23,
            "nome": "Notebook Renan",
            "host": "192.168.200.122",
            "enderecos_adicionais": "[]",
            "ultima_detalhes": "{}",
        }]
        registered = portal.technology_registered_device_hosts(rows)

        self.assertEqual("Notebook Renan", registered["192.168.200.10"])
        self.assertEqual("Notebook Renan", registered["192.168.200.122"])
        self.assertEqual("Notebook Renan", registered["100.66.72.69"])

        index = portal.technology_registered_device_index(rows)
        self.assertEqual(13, portal.technology_registered_device_match(
            index, host="192.168.200.122",
        )["id"])
        self.assertEqual(13, portal.technology_registered_device_match(
            index, identity_name="RENAN-NOTE",
        )["id"])

    def test_device_address_conflict_checks_secondary_addresses(self):
        rows = [{
            "id": 13,
            "nome": "Notebook Renan",
            "host": "192.168.200.10",
            "enderecos_adicionais": json.dumps([
                {"label": "Wi-Fi", "host": "192.168.200.122"},
            ]),
        }]

        conflict = portal.technology_device_address_conflict({
            "host": "192.168.200.122", "enderecos_adicionais": "[]",
        }, rows)
        own_update = portal.technology_device_address_conflict({
            "host": "192.168.200.122", "enderecos_adicionais": "[]",
        }, rows, exclude_device_id=13)

        self.assertEqual("192.168.200.122", conflict[0])
        self.assertEqual(13, conflict[1]["id"])
        self.assertIsNone(own_update)

    def test_initial_devices_consider_secondary_addresses(self):
        source = (PROJECT_DIR / "app.py").read_text(encoding="utf-8")

        self.assertIn(
            "JSON_SEARCH(enderecos_adicionais, 'one', %s, NULL, '$[*].host')",
            source,
        )

    def test_technology_database_timestamp_is_serialized_as_utc(self):
        checked_at = dt.datetime(2026, 8, 22, 10, 23, 6, 123000)

        self.assertEqual(
            "2026-08-22T10:23:06.123Z",
            portal.technology_db_timestamp_iso(checked_at),
        )

    def test_printer_page_usage_compares_daily_counter_and_ignores_reset(self):
        def sample(checked_at, page_count):
            return {
                "verificado_em": checked_at,
                "detalhes": json.dumps({"telemetry": {"pageCount": page_count}}),
            }

        usage = portal.technology_printer_page_usage([
            sample(dt.datetime(2026, 8, 16, 2, 59), 100),   # sábado 23:59 local
            sample(dt.datetime(2026, 8, 16, 13, 0), 105),   # domingo
            sample(dt.datetime(2026, 8, 17, 13, 0), 112),   # segunda
            sample(dt.datetime(2026, 8, 18, 13, 0), 3),     # contador reiniciado
            sample(dt.datetime(2026, 8, 19, 12, 0), 8),     # quarta
        ], now=dt.datetime(2026, 8, 19, 15, 0, tzinfo=dt.UTC))

        self.assertEqual("2026-08-16", usage["periodStart"])
        self.assertEqual("2026-08-19", usage["periodEnd"])
        self.assertEqual([5, 7, 0, 5], [day["pages"] for day in usage["days"]])
        self.assertEqual(5, usage["todayPages"])
        self.assertEqual(17, usage["weekPages"])
        self.assertTrue(usage["hasComparisons"])
        self.assertTrue(usage["todayComplete"])

        partial_today = portal.technology_printer_page_usage([
            sample(dt.datetime(2026, 8, 22, 11, 0), 200),
            sample(dt.datetime(2026, 8, 22, 12, 0), 206),
        ], now=dt.datetime(2026, 8, 22, 15, 0, tzinfo=dt.UTC))
        self.assertEqual(6, partial_today["todayPages"])
        self.assertFalse(partial_today["todayComplete"])
        self.assertEqual("2026-08-22T11:00:00.000Z", partial_today["coverageStartedAt"])

    def test_technology_public_metric_preserves_utc_timezone(self):
        metric = portal.technology_public_metric({
            "ultima_status": "ONLINE",
            "ultima_verificado_em": dt.datetime(2026, 8, 22, 10, 23),
            "ultima_perda_pct": 0,
            "ultima_mensagem": "resposta normal",
        }, "ultima_")

        self.assertEqual("2026-08-22T10:23:00.000Z", metric["checkedAt"])

    def test_technology_alert_uses_existing_riob_smtp_account(self):
        riob_account = {
            "host": "smtps.bol.com.br", "port": 587,
            "user": "remetente@bol.com.br", "password": "stored-secret",
            "sender": "remetente@bol.com.br", "useTls": True,
            "source": "riob", "accountName": "Compras",
        }
        environment = {
            "SMTP_HOST": "", "SMTP_USER": "", "SMTP_PASSWORD": "", "SMTP_FROM": "",
            "TECH_ALERT_EMAIL_TO": "solucoestecnologicasrenan@gmail.com",
        }
        with (
            mock.patch.dict(portal.os.environ, environment, clear=False),
            mock.patch.object(portal, "technology_riob_smtp_config", return_value=riob_account),
        ):
            config = portal.technology_email_config()

        self.assertTrue(config["configured"])
        self.assertEqual("remetente@bol.com.br", config["sender"])
        self.assertEqual("solucoestecnologicasrenan@gmail.com", config["recipient"])
        self.assertEqual("riob", config["source"])

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

    def test_temporary_recipient_refusal_has_readable_message(self):
        error = smtplib.SMTPRecipientsRefused({
            "destino@example.test": (450, b"4.7.1 Recipient address rejected: SMTP-02"),
        })

        message = portal.technology_smtp_error_message(error)

        self.assertIn("recusou temporariamente", message)
        self.assertIn("destino@example.test", message)
        self.assertIn("450", message)

    def test_successful_email_clears_stale_smtp_errors(self):
        conn = mock.MagicMock()
        cursor = conn.cursor.return_value
        with mock.patch.object(portal, "get_conn", return_value=conn):
            portal.technology_clear_email_errors()

        cursor.execute.assert_called_once_with(
            "UPDATE tecnologia_alertas_recursos SET ultimo_erro='' WHERE ultimo_erro<>''"
        )
        conn.commit.assert_called_once_with()
        cursor.close.assert_called_once_with()
        conn.close.assert_called_once_with()

    def test_internal_drop_does_not_become_email_alert_but_internet_drop_does(self):
        internal = portal.technology_alert_telemetry(
            {"tipo": "SERVIDOR"}, {"status": "OFFLINE", "details": {}},
        )
        internet = portal.technology_alert_telemetry(
            {"tipo": "INTERNET"}, {"status": "OFFLINE", "details": {}},
        )

        self.assertNotIn("internetDownState", internal)
        self.assertEqual(100, internet["internetDownState"])
        self.assertIn("sem resposta", internet["internetDownAlertDescription"])

    def test_gateway_degradation_becomes_email_alert_and_online_is_recovery(self):
        device = {"tipo": "ROTEADOR"}
        degraded = portal.technology_alert_telemetry(
            device,
            {"status": "DEGRADADO", "message": "perda 25%", "details": {}},
        )
        recovered = portal.technology_alert_telemetry(
            device,
            {"status": "ONLINE", "message": "resposta normal", "details": {}},
        )

        self.assertEqual(100, degraded["gatewayFailureState"])
        self.assertIn("perda 25%", degraded["gatewayFailureAlertDescription"])
        self.assertEqual(0, recovered["gatewayFailureState"])
        self.assertIn("voltou", recovered["gatewayFailureRecoveryDescription"])

    def test_low_internet_speed_creates_only_link_speed_alert(self):
        internet = {
            "id": 1, "nome": "Link", "host": "1.1.1.1", "tipo": "INTERNET",
            "download_alerta_mbps": 50, "upload_alerta_mbps": 10,
        }
        speed = {"status": "DEGRADADO", "downloadMbps": 20, "uploadMbps": 12}
        with mock.patch.object(portal, "process_technology_resource_alerts", return_value=[{"type": "ALERTA"}]) as process:
            actions = portal.process_technology_link_speed_alert(internet, speed)

        self.assertEqual([{"type": "ALERTA"}], actions)
        synthetic = process.call_args.args[1][0]["details"]["telemetry"]
        self.assertEqual(100, synthetic["linkSlowState"])
        self.assertIn("download baixo", synthetic["linkSlowAlertDescription"])
        self.assertNotIn("upload baixo", synthetic["linkSlowAlertDescription"])

    def test_network_resource_email_threshold_is_ninety_percent(self):
        self.assertEqual(("networkPct", None, "uso da rede", 90), portal.TECH_ALERT_RESOURCES["REDE"])

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
        self.assertIn("GET", routes["/apps/tecnologia/api/devices/<int:device_id>/print-usage"])

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
        self.assertIn("Remetente:", javascript)
        self.assertIn("identityName: button.dataset.computerName", javascript)
        self.assertIn("Impressões da semana", javascript)
        self.assertIn("/print-usage", javascript)
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
