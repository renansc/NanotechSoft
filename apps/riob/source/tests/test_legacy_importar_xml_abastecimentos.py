import unittest
from unittest.mock import patch

from flask import Flask

import legacy_services


class LegacyImportarXmlAbastecimentosTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test"
        self.app.register_blueprint(legacy_services.XML_BP)
        self.app.register_blueprint(legacy_services.EMAIL_BP)
        self.client = self.app.test_client()

    def test_pending_form_normalizes_vehicle_and_values(self):
        result = legacy_services._abastecimento_pending_form(
            {
                "combustivel": "diesel_500",
                "km_final": "184500",
                "posto_nome": "Posto Teste",
                "data_emissao": "2026-06-13T10:30",
                "motorista": "Renan",
                "litros": "40,5",
                "valor_total": "250,75",
            },
            {"id": 15, "placa": "AKL-5B81"},
        )

        self.assertEqual(15, result["veiculo_id"])
        self.assertEqual("AKL-5B81", result["placa"])
        self.assertEqual("OLEO DIESEL B S500", result["combustivel"])
        self.assertEqual(40.5, result["litros"])
        self.assertEqual(250.75, result["valor_total"])

    def test_pending_form_accepts_gasolina_and_etanol(self):
        vehicle = {"id": 77, "placa": "ABC-1D23"}
        base = {
            "km_final": "50000",
            "posto_nome": "Posto Teste",
            "data_emissao": "2026-06-13T10:30",
            "litros": "30",
            "valor_total": "180",
        }

        gasolina = legacy_services._abastecimento_pending_form(
            {**base, "combustivel": "gasolina"},
            vehicle,
        )
        etanol = legacy_services._abastecimento_pending_form(
            {**base, "combustivel": "etanol"},
            vehicle,
        )

        self.assertEqual("GASOLINA COMUM", gasolina["combustivel"])
        self.assertEqual("ETANOL HIDRATADO COMUM", etanol["combustivel"])

    def test_pending_review_page_exposes_edit_and_ignore_actions(self):
        source = {
            "id": 9,
            "numero_nota": "98247",
            "data_emissao": "2026-06-02T14:43:24-03:00",
            "posto_nome": "AUTO POSTO",
            "placa": "AKL5B81",
            "km_final": 1,
            "motorista": "OSVALDO",
            "combustivel": "OLEO DIESEL B S500",
            "litros": 40,
            "valor_produto": 255.6,
            "valor_total": 247.6,
            "chave_nfe": "4" * 44,
            "vinculo_status": "pendente",
            "vinculo_motivo": "KM incompativel",
            "vinculo_veiculo_id": 15,
        }
        vehicles = [
            {
                "id": 15,
                "nome": "51",
                "placa": "AKL-5B81",
                "modelo": "TRUCK",
                "combustivel_padrao": "diesel_500",
                "km_atual": 184331,
            }
        ]
        with (
            patch.object(legacy_services, "_row", return_value=source),
            patch.object(legacy_services, "_rows", return_value=vehicles),
        ):
            response = self.client.get("/importar-xml/abastecimentos/9")

        text = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Salvar e finalizar", text)
        self.assertIn("Ignorar esta pendencia", text)
        self.assertIn("AKL-5B81", text)
        self.assertIn("KM incompativel", text)

    def test_pending_review_updates_source_and_runs_existing_sync(self):
        source = {
            "id": 9,
            "numero_nota": "98247",
            "vinculo_status": "pendente",
        }
        vehicle = {
            "id": 15,
            "placa": "AKL-5B81",
            "combustivel_padrao": "diesel_500",
        }
        result = {
            "status": "criado",
            "motivo": "Criado",
            "abastecimento_id": 123,
        }
        callback_calls = []

        with (
            patch.object(
                legacy_services,
                "_row",
                side_effect=[source, vehicle, result],
            ),
            patch.object(legacy_services, "_execute") as execute,
            patch.object(
                legacy_services,
                "_abastecimento_import_callback",
                side_effect=lambda xml_id: callback_calls.append(xml_id),
            ),
        ):
            response = self.client.post(
                "/importar-xml/abastecimentos/9",
                data={
                    "acao": "finalizar",
                    "veiculo_id": "15",
                    "km_final": "184500",
                    "combustivel": "diesel_500",
                    "litros": "40",
                    "valor_total": "255.60",
                    "data_emissao": "2026-06-02T14:43",
                    "posto_nome": "AUTO POSTO",
                    "motorista": "OSVALDO",
                },
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual([9], callback_calls)
        execute.assert_called_once()
        self.assertIn("/importar-xml/abastecimentos", response.location)

    def test_pending_review_rejects_invalid_vehicle_id(self):
        source = {
            "id": 9,
            "numero_nota": "98247",
            "vinculo_status": "pendente",
        }
        with (
            patch.object(
                legacy_services,
                "_row",
                side_effect=[source, None],
            ),
            patch.object(legacy_services, "_execute") as execute,
            patch.object(
                legacy_services,
                "_abastecimento_import_callback",
            ) as callback,
        ):
            response = self.client.post(
                "/importar-xml/abastecimentos/9",
                data={
                    "acao": "finalizar",
                    "veiculo_id": "invalido",
                },
            )

        self.assertEqual(302, response.status_code)
        execute.assert_not_called()
        callback.assert_not_called()

    def test_pending_review_can_be_ignored_without_sync(self):
        source = {
            "id": 44,
            "numero_nota": "98178",
            "vinculo_status": "pendente",
        }
        with (
            patch.object(legacy_services, "_row", return_value=source),
            patch.object(legacy_services, "_execute") as execute,
            patch.object(
                legacy_services,
                "_abastecimento_import_callback",
            ) as callback,
        ):
            response = self.client.post(
                "/importar-xml/abastecimentos/44",
                data={
                    "acao": "ignorar",
                    "motivo_ignorar": "Item de manutencao, nao e combustivel.",
                },
            )

        self.assertEqual(302, response.status_code)
        execute.assert_called_once()
        callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
