"""Network consumption uses only comparable samples from the local day."""
import datetime as dt
import json
import unittest
from unittest import mock

import app as portal
from apps.tecnologia import monitor


class NetworkBootstrapTests(unittest.TestCase):
    def bootstrap(self, table_exists, profile="rio-branco", count=0):
        conn = mock.MagicMock()
        cur = conn.cursor.return_value

        def fetchone():
            sql = cur.execute.call_args.args[0]
            if "information_schema.tables" in sql:
                return (1,) if table_exists else None
            if "COUNT(*) FROM tecnologia_dispositivos" in sql:
                return (count,)
            if "SELECT id FROM tecnologia_dispositivos" in sql:
                return None
            return (1,)

        cur.fetchone.side_effect = fetchone
        with mock.patch.object(portal, "_db_ready", False), mock.patch.object(portal, "CLOUD_READ_ONLY", False), \
                mock.patch.object(portal, "ensure_mysql_database"), mock.patch.object(portal, "get_conn", return_value=conn), \
                mock.patch.object(portal, "configured_client_id", return_value=profile), \
                mock.patch.object(portal, "generate_password_hash", return_value="fixture"):
            portal.ensure_database()
        return [call for method in (cur.execute, cur.executemany) for call in method.call_args_list
                if "INSERT INTO tecnologia_dispositivos" in call.args[0]]

    def test_existing_inventory_never_recreates_deleted_or_old_ips(self):
        for count in (0, 16):
            with self.subTest(count=count):
                self.assertEqual([], self.bootstrap(table_exists=True, count=count))

    def test_only_first_creation_in_rio_branco_seeds_devices(self):
        self.assertEqual(9, len(self.bootstrap(table_exists=False)))
        self.assertEqual([], self.bootstrap(table_exists=False, profile="nanotech"))


class NetworkUsageTests(unittest.TestCase):
    now = dt.datetime(2026, 9, 23, 15, tzinfo=dt.UTC)

    def sample(self, hour, rx, tx, source="ifXTable64", uptime=100):
        return {"verificado_em": self.now.replace(hour=hour, tzinfo=None),
                "detalhes": json.dumps({"telemetry": {
                    "protocol": "SNMPv2c", "interfaces": ["eth0"], "uptimeSeconds": uptime,
                    "counters": {"source": source, "rxBytes": rx, "txBytes": tx}}})}

    def test_local_midnight_excludes_previous_day_and_future_samples(self):
        report = portal.technology_network_day_usage([
            self.sample(2, 0, 0), self.sample(3, 100, 200),
            self.sample(4, 400, 700), self.sample(16, 9000, 9000)], self.now)
        self.assertEqual(300, report["downloadBytes"])
        self.assertEqual(500, report["uploadBytes"])
        self.assertEqual(800, report["totalBytes"])
        self.assertEqual("2026-09-23T03:00:00.000Z", report["measuredFrom"])

    def test_missing_counters_and_single_sample_are_not_zero(self):
        for rows in ([], [self.sample(4, 100, 200)], [self.sample(4, None, None), self.sample(5, None, None)]):
            self.assertIsNone(portal.technology_network_day_usage(rows, self.now)["totalBytes"])
        report = portal.technology_network_day_usage([self.sample(4, 100, 200), self.sample(5, 100, 200)], self.now)
        self.assertEqual(0, report["totalBytes"])

    def test_restart_decrease_and_source_change_do_not_inflate_usage(self):
        rows = [self.sample(3, 100, 100), self.sample(4, 200, 200),
                self.sample(5, 20, 20), self.sample(6, 40, 40),
                self.sample(7, 9000, 9000, source="ifTable32"),
                self.sample(8, 9010, 9010, source="ifTable32")]
        report = portal.technology_network_day_usage(rows, self.now)
        self.assertEqual(260, report["totalBytes"])
        self.assertGreater(report["omittedIntervals"], 0)
        report = portal.technology_network_day_usage([
            self.sample(4, 10, 10, uptime=1000), self.sample(5, 10000, 10000, uptime=10)], self.now)
        self.assertIsNone(report["totalBytes"])

    def test_missing_direction_does_not_produce_a_total(self):
        report = portal.technology_network_day_usage([self.sample(4, 10, None), self.sample(5, 20, None)], self.now)
        self.assertEqual(10, report["downloadBytes"])
        self.assertIsNone(report["uploadBytes"])
        self.assertIsNone(report["totalBytes"])

    def test_network_query_bounds_and_missing_device(self):
        conn = mock.MagicMock()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"id": 7}
        cur.fetchall.return_value = []
        with portal.app.test_request_context(), mock.patch.object(portal, "get_conn", return_value=conn):
            response = portal.tecnologia_network_device_api.__wrapped__(7)
        self.assertIsNone(response.json["totalBytes"])
        args = cur.execute.call_args.args[1]
        self.assertEqual(7, args[0])
        self.assertEqual(3, args[1].hour)
        cur.close.assert_called_once()
        conn.close.assert_called_once()
        cur.fetchone.return_value = None
        with portal.app.test_request_context(), mock.patch.object(portal, "get_conn", return_value=conn):
            self.assertEqual(404, portal.tecnologia_network_device_api.__wrapped__(7)[1])

    def test_mac_normalization_and_exporter_collection(self):
        self.assertEqual(["AA:BB:CC:DD:EE:FF"], monitor.network_mac_addresses([
            "aa bb cc dd ee ff", "aa-bb-cc-dd-ee-ff", "00:00:00:00:00:00", "invalid"]))
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'node_memory_MemTotal_bytes 1000\nnode_network_info{device="eth0",address="aa:bb:cc:dd:ee:ff"} 1\n'
        with mock.patch.object(monitor.urllib.request, "urlopen", return_value=response):
            telemetry = monitor.collect_prometheus_metrics({"host": "192.0.2.1", "agente_porta": 9100})
        self.assertEqual(["AA:BB:CC:DD:EE:FF"], telemetry["macAddresses"])
        self.assertIsNone(telemetry["counters"]["rxBytes"])


class NetworkMacTests(unittest.TestCase):
    table = """IP address HW type Flags HW address Mask Device
192.0.2.7 0x1 0x2 aa:bb:cc:dd:ee:ff * eno2
192.0.2.8 0x1 0x0 00:00:00:00:00:00 * eno2
192.0.2.9 0x1 0x2 01:00:5e:00:00:01 * eno2
192.0.2.10 0x1 invalid aa:bb:cc:dd:ee:00 * eno2
192.0.2.11 0x1 0x2 aa:bb:cc:dd:ee:01 * eno2
192.0.2.11 0x1 0x2 aa:bb:cc:dd:ee:02 * eno3
192.0.2.1 0x1 0x2 02:00:00:00:00:01 * eno2
"""

    def test_arp_matches_only_exact_complete_unicast_neighbors(self):
        addresses = [{"host": f"192.0.2.{n}"} for n in (7, 8, 9, 10, 11, 12)]
        addresses += [{"host": "unknown.local"}, {"host": "::1"}]
        with mock.patch.object(monitor.Path, "read_text", return_value=self.table):
            result = monitor.arp_mac_observations(addresses)
        self.assertEqual([{"host": "192.0.2.7", "mac": "AA:BB:CC:DD:EE:FF", "interface": "eno2"}], result)

    def test_missing_or_unreadable_table_does_not_fail_probe(self):
        with mock.patch.object(monitor.Path, "read_text", side_effect=PermissionError):
            self.assertEqual([], monitor.arp_mac_observations([{"host": "192.0.2.7"}]))

    def test_protocol_mac_has_priority_over_arp(self):
        with mock.patch.object(monitor, "arp_mac_observations") as arp:
            result = monitor.device_mac_identity([{"host": "192.0.2.7"}], {"protocol": "SNMPv2c", "macAddresses": ["aa:bb:cc:dd:ee:ff"]})
        arp.assert_not_called()
        self.assertEqual("SNMPv2c", result["macSource"])

    def test_icmp_probe_stores_arp_identity_without_fake_telemetry(self):
        with mock.patch.object(monitor.Path, "read_text", return_value=self.table), \
                mock.patch.object(monitor, "ping_host", return_value={"reachable": True, "packetLossPct": 0, "latencyMs": 1}):
            result = monitor.probe_device({"host": "192.0.2.7", "sonda": "ICMP", "tipo": "ROTEADOR"})
        self.assertEqual("ARP", result["details"]["macSource"])
        self.assertEqual(["AA:BB:CC:DD:EE:FF"], result["details"]["macAddresses"])
        self.assertIsNone(result["details"]["telemetry"])
        with mock.patch.object(portal, "CLOUD_READ_ONLY", True), mock.patch.object(monitor.Path, "read_text") as read:
            metric = portal.technology_public_metric({"status": "ONLINE", "detalhes": result["details"]})
        read.assert_not_called()
        self.assertEqual("ARP", metric["macSource"])
        self.assertEqual("192.0.2.7", metric["macObservations"][0]["host"])

    def test_add_device_collects_only_new_device_after_commit(self):
        for active, fail in ((True, False), (True, True), (False, False)):
            with self.subTest(active=active, fail=fail):
                conn = mock.MagicMock()
                conn.cursor.return_value.lastrowid = 42
                def collect(ids):
                    conn.commit.assert_called_once()
                    self.assertEqual([42], ids)
                    if fail:
                        raise RuntimeError("fixture")
                    return []
                with portal.app.test_request_context("/apps/tecnologia/api/devices", method="POST", json={
                        "nome": "Teste", "host": "192.0.2.7", "tipo": "ROTEADOR", "ativo": active}), \
                        mock.patch.object(portal, "technology_admin_or_error", return_value=None), \
                        mock.patch.object(portal, "get_technology_devices", return_value=[]), \
                        mock.patch.object(portal, "get_conn", return_value=conn), \
                        mock.patch.object(portal, "collect_technology_metrics", side_effect=collect) as probe, \
                        mock.patch.object(portal, "start_technology_monitor") as start:
                    response, status = portal.tecnologia_create_device_api.__wrapped__()
                self.assertEqual(201, status)
                self.assertEqual(42, response.json["id"])
                self.assertEqual(fail, bool(response.json["warning"]))
                self.assertEqual(int(active), probe.call_count)
                self.assertEqual(int(active), start.call_count)

    def test_non_admin_cannot_add_or_trigger_initial_probe(self):
        with portal.app.test_request_context("/apps/tecnologia/api/devices", method="POST", json={}), \
                mock.patch.object(portal, "current_user_or_logout", return_value={"id": 1, "perfil": "usuario"}), \
                mock.patch.object(portal, "collect_technology_metrics") as collect, \
                mock.patch.object(portal, "get_conn") as conn:
            self.assertEqual(403, portal.tecnologia_create_device_api.__wrapped__()[1])
        collect.assert_not_called()
        conn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
