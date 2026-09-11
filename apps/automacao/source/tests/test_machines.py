import tempfile
import unittest
from pathlib import Path

import database
from app import app


class MachineMonitoringTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_NAME = Path(self.temp_dir.name) / "automacao-test.db"
        database.init_database()
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_catalog_seeds_two_documented_machines(self):
        response = self.client.get("/api/maquinas")
        self.assertEqual(response.status_code, 200)
        machines = response.get_json()["maquinas"]
        self.assertEqual(len(machines), 2)
        self.assertEqual(
            {machine["slug"] for machine in machines},
            {
                "empacotadora-rodighero-er1500",
                "brix-zegla-unimix-20000l",
            },
        )
        self.assertTrue(all(machine["pontos"] for machine in machines))

    def test_gateway_reading_updates_status_and_alarm(self):
        response = self.client.post(
            "/api/maquinas/empacotadora-rodighero-er1500/leituras",
            json={
                "pontos": {
                    "contador_pacotes": 42,
                    "pressao_ar_bar": 4.2,
                    "emergencia_acionada": False,
                }
            },
        )
        self.assertEqual(response.status_code, 201)
        result = response.get_json()
        self.assertEqual(result["status"], "alarme")
        self.assertEqual(result["alarmes"][0]["ponto"], "pressao_ar_bar")

        latest = self.client.get(
            "/api/maquinas/empacotadora-rodighero-er1500/ultima"
        ).get_json()
        self.assertEqual(latest["dados"]["contador_pacotes"], 42)
        self.assertEqual(latest["status"], "alarme")

    def test_unknown_points_do_not_create_uncontrolled_tags(self):
        response = self.client.post(
            "/api/maquinas/brix-zegla-unimix-20000l/leituras",
            json={"pontos": {"registrador_inventado": 123}},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json()["ignorados"],
            ["registrador_inventado"],
        )

    def test_machine_and_documentation_pages_render(self):
        machine = self.client.get(
            "/maquinas/brix-zegla-unimix-20000l"
        )
        documentation = self.client.get(
            "/documentacao/empacotadora-rodighero-er1500"
        )
        self.assertEqual(machine.status_code, 200)
        self.assertIn(b"Zegla Unimix", machine.data)
        self.assertEqual(documentation.status_code, 200)
        self.assertIn(b"Rodighero ER-1500", documentation.data)


if __name__ == "__main__":
    unittest.main()
