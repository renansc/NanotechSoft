import tempfile
import unittest
from unittest import mock
from pathlib import Path

import database
from app import app
from machine_catalog import MACHINES, DOCUMENTED_MACHINES, documented_machine_by_slug


class MachineMonitoringTest(unittest.TestCase):
    def setUp(self):
        profile = mock.patch.dict("os.environ", {"CLIENTE_DEPLOY_ID": "rio-branco"})
        profile.start()
        self.addCleanup(profile.stop)
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_NAME = Path(self.temp_dir.name) / "automacao-test.db"
        database.init_database()
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_catalog_seeds_three_documented_machines(self):
        response = self.client.get("/api/maquinas")
        self.assertEqual(response.status_code, 200)
        machines = response.get_json()["maquinas"]
        self.assertEqual(len(machines), 3)
        self.assertEqual(
            {machine["slug"] for machine in machines},
            {
                "empacotadora-rodighero-er1500",
                "brix-zegla-unimix-20000l",
                "impressora-laser-cyklop",
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

    def test_all_documented_machines_have_working_guides_and_pdfs(self):
        listing=self.client.get('/documentacao')
        self.assertEqual(200,listing.status_code)
        for machine in DOCUMENTED_MACHINES:
            guide='/documentacao/'+machine['slug']
            pdf='/static/'+machine['documentacao']['arquivo']
            with self.subTest(machine=machine['slug']):
                self.assertIn(guide.encode(),listing.data)
                self.assertIn(pdf.encode(),listing.data)
                self.assertEqual(200,self.client.get(guide).status_code)
                response=self.client.get(pdf)
                self.assertEqual(200,response.status_code)
                self.assertEqual('application/pdf',response.mimetype)
                self.assertTrue(response.data.startswith(b'%PDF'))
                response.close()

    def test_envasadora_documento_e_distinto_da_brix_e_nao_cria_telemetria(self):
        envasadora=documented_machine_by_slug('envasadora-zegla-40-50-10-ga')
        brix=documented_machine_by_slug('brix-zegla-unimix-20000l')
        self.assertEqual('RZ-RET-G-40/50/10-GA-GII',envasadora['modelo'])
        self.assertEqual('RZ-UC-20',brix['modelo'])
        self.assertNotEqual(envasadora['documentacao']['arquivo'],brix['documentacao']['arquivo'])
        response=self.client.get('/documentacao/'+envasadora['slug'])
        self.assertEqual(200,response.status_code)
        self.assertIn(b'2000164575',response.data)
        self.assertIn(envasadora['documentacao']['arquivo'].encode(),response.data)
        self.assertNotIn(b'/maquinas/envasadora-zegla',response.data)
        self.assertEqual(3,len(self.client.get('/api/maquinas').json['maquinas']))
        self.assertIsNone(documented_machine_by_slug('maquina-inexistente'))

    def test_cyklop_waits_for_real_readings_and_preserves_history_on_startup(self):
        slug = "impressora-laser-cyklop"
        machines = self.client.get("/api/maquinas").json["maquinas"]
        machine = next(item for item in machines if item["slug"] == slug)
        self.assertEqual("aguardando", machine["ultimo_status"])
        self.assertEqual({}, self.client.get(f"/api/maquinas/{slug}/ultima").json)
        self.assertEqual(6, len(machine["pontos"]))
        data = {"placa_conectada": True, "estado_marcacao": 2,
                "contador_total": 1200, "contador_atual": 30,
                "marcacoes_perdidas": 2, "tempo_marcacao_ms": 100}
        result = self.client.post(f"/api/maquinas/{slug}/leituras", json={"pontos": data})
        self.assertEqual(201, result.status_code)
        self.assertEqual("online", result.json["status"])
        database.init_database()
        self.assertEqual(data, self.client.get(f"/api/maquinas/{slug}/ultima").json["dados"])
        machines = self.client.get("/api/maquinas").json["maquinas"]
        self.assertEqual(1, sum(item["slug"] == slug for item in machines))
        self.assertEqual(6, len(next(item for item in machines if item["slug"] == slug)["pontos"]))
        result = self.client.post(f"/api/maquinas/{slug}/leituras", json={"pontos": {"placa_conectada": False}})
        self.assertEqual("alarme", result.json["status"])
        self.assertEqual("placa_conectada", result.json["alarmes"][0]["ponto"])

    def test_cyklop_protocol_label_and_monitoring_links(self):
        slug = "impressora-laser-cyklop"
        self.assertIn(f'/maquinas/{slug}'.encode(), self.client.get('/maquinas').data)
        for path in (f"/documentacao/{slug}", f"/maquinas/{slug}"):
            response = self.client.get(path)
            self.assertEqual(200, response.status_code)
            self.assertIn("Protocolo de comunicação em PDF".encode(), response.data)
            self.assertNotIn(b"Manual fotografado", response.data)

    def test_cyklop_is_not_seeded_in_other_clients(self):
        for client in ("nanotech", "laboratorio", "senhor", "cloud", ""):
            with self.subTest(client=client), mock.patch.dict("os.environ", {
                "CLIENTE_DEPLOY_ID": client, "NANOTECH_DEPLOY_PROFILE": client,
            }):
                database.DB_NAME = Path(self.temp_dir.name) / f"{client or 'unconfigured'}.db"
                database.init_database()
                slugs = {item["slug"] for item in self.client.get("/api/maquinas").json["maquinas"]}
                self.assertNotIn("impressora-laser-cyklop", slugs)
                self.assertFalse(slugs, "Cadastros do Rio Branco nao podem ser semeados em outro cliente")


if __name__ == "__main__":
    unittest.main()
