import unittest
from unittest import mock

import app as portal
from apps.tecnologia import monitor


class NetworkScanTests(unittest.TestCase):
    devices = [{"host": "192.168.1.1", "ativo": False,
                "networkAddresses": [{"host": "192.168.1.2"}],
                "ultimaMetrica": {"macAddresses": ["AA:BB:CC:DD:EE:01"]}}]

    def test_scope_is_private_bounded_and_derived_from_inventory(self):
        self.assertEqual(["192.168.1.0/24"], monitor.network_scan_subnets(self.devices))
        self.assertEqual(["192.168.1.0/24", "10.0.0.0/24"], monitor.network_scan_subnets([
            {"host": "10.0.0.1"}, *self.devices]))
        self.assertEqual([], monitor.network_scan_subnets([
            {"host": host} for host in ("8.8.8.8", "127.0.0.1", "::1", "localhost", "169.254.1.1")]))
        with mock.patch.object(monitor, "scan_network_host") as probe:
            for subnet in ("0.0.0.0/0", "192.168.1.0/16", "10.0.0.0/24", "bad"):
                with self.assertRaises(ValueError):
                    monitor.scan_unregistered_network(subnet, self.devices)
            probe.assert_not_called()

    def test_excludes_primary_additional_and_same_mac_even_when_inactive(self):
        def probe(host):
            return {"ip": host, "name": "", "mac": ""} if host.endswith((".3", ".4", ".5")) else None
        observations = [{"host": "192.168.1.3", "mac": "AA:BB:CC:DD:EE:01"},
                        {"host": "192.168.1.2", "mac": "AA:BB:CC:DD:EE:02"},
                        {"host": "192.168.1.4", "mac": "AA:BB:CC:DD:EE:02"},
                        {"host": "192.168.1.6", "mac": "AA:BB:CC:DD:EE:06"}]
        with mock.patch.object(monitor, "scan_network_host", side_effect=probe) as check, \
                mock.patch.object(monitor, "arp_mac_observations", return_value=observations):
            found = monitor.scan_unregistered_network("192.168.1.0/24", self.devices)
        self.assertEqual([{"ip": "192.168.1.5", "name": "", "mac": ""}], found)
        self.assertNotIn(mock.call("192.168.1.1"), check.call_args_list)
        self.assertNotIn(mock.call("192.168.1.2"), check.call_args_list)
        self.assertEqual(252, check.call_count)

    def test_presence_requires_response_and_dns_alone_is_not_presence(self):
        with mock.patch.object(monitor, "ping_host", return_value={"reachable": False}), \
                mock.patch.object(monitor, "netbios_node_status", return_value={"ok": False}), \
                mock.patch.object(monitor, "tcp_host", return_value={"reachable": False}) as tcp, \
                mock.patch.object(monitor.subprocess, "run") as dns:
            self.assertIsNone(monitor.scan_network_host("192.168.1.5"))
            dns.assert_not_called()
            tcp.return_value = {"reachable": False, "error": "ConnectionRefusedError"}
            dns.side_effect = FileNotFoundError
            self.assertEqual("", monitor.scan_network_host("192.168.1.5")["name"])
        with mock.patch.object(monitor, "ping_host", return_value={"reachable": True}), \
                mock.patch.object(monitor, "netbios_node_status", return_value={"ok": True, "name": "ESTACAO"}):
            self.assertEqual("ESTACAO", monitor.scan_network_host("192.168.1.5")["name"])

    def test_authorization_requires_both_resources_before_menu_shortcut(self):
        for resources, allowed in [({"rede"}, False), ({"rede_scan"}, False),
                                   ({"rede", "rede_scan"}, True), ({"*"}, True)]:
            with self.subTest(resources=resources), \
                    portal.app.test_request_context("/apps/tecnologia/api/network/scan", method="POST"), \
                    mock.patch.object(portal, "allowed_app_keys", return_value={"tecnologia"}), \
                    mock.patch.object(portal, "current_user_or_logout", return_value={"id": 42, "perfil": "usuario"}), \
                    mock.patch.object(portal, "get_user_permissions", return_value={"tecnologia": resources}):
                response = portal.enforce_app_permission()
                self.assertIsNone(response) if allowed else self.assertEqual(403, response[1])

    def test_route_is_read_only_and_unlocks_on_validation_failure(self):
        with portal.app.test_request_context(json={"subnet": "192.168.1.0/24"}), \
                mock.patch.object(portal, "CLOUD_READ_ONLY", False), \
                mock.patch.object(portal, "current_user_or_logout", return_value={"id": 1}), \
                mock.patch.object(portal, "can_access", return_value=True), \
                mock.patch.object(portal, "get_technology_devices", return_value=[]), \
                mock.patch.object(portal, "scan_unregistered_network", return_value=[]) as scan, \
                mock.patch.object(portal, "get_conn") as conn, \
                mock.patch.object(portal, "collect_technology_metrics") as collect:
            self.assertEqual([], portal.tecnologia_network_scan_api.__wrapped__().json["devices"])
            conn.assert_not_called()
            collect.assert_not_called()
            scan.side_effect = ValueError("invalid")
            self.assertEqual(400, portal.tecnologia_network_scan_api.__wrapped__()[1])
            self.assertFalse(portal._technology_scan_lock.locked())
            with mock.patch.object(portal, "CLOUD_READ_ONLY", True):
                scan.reset_mock()
                self.assertEqual(403, portal.tecnologia_network_scan_api.__wrapped__()[1])
                scan.assert_not_called()
            portal._technology_scan_lock.acquire()
            try:
                self.assertEqual(409, portal.tecnologia_network_scan_api.__wrapped__()[1])
            finally:
                portal._technology_scan_lock.release()


if __name__ == "__main__":
    unittest.main()
