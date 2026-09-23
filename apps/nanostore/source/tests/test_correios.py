import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nanostore.correios import CorreiosClient, CorreiosError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class CorreiosClientTest(unittest.TestCase):
    def make_client(self):
        return CorreiosClient({
            "NANOSTORE_CORREIOS_API_URL": "https://api.example.test",
            "NANOSTORE_CORREIOS_USERNAME": "usuario",
            "NANOSTORE_CORREIOS_ACCESS_CODE": "codigo",
            "NANOSTORE_CORREIOS_POSTING_CARD": "1234567890",
            "NANOSTORE_CORREIOS_ORIGIN_POSTAL_CODE": "80000-000",
            "NANOSTORE_CORREIOS_SERVICE_CODE": "SERVICO1",
        })

    def test_public_status_never_exposes_credentials(self):
        status = self.make_client().public_status()
        self.assertTrue(status["configured"])
        self.assertEqual("80000000", status["origin_postal_code"])
        self.assertNotIn("username", status)
        self.assertNotIn("access_code", status)
        self.assertNotIn("posting_card", status)

    def test_estimates_delivery_with_token_and_official_deadline_response(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request, timeout))
            if "/token/" in request.full_url:
                return FakeResponse({"token": "TOKEN", "expiraEm": "2099-01-01T00:00:00Z"})
            return FakeResponse([{"prazoEntrega": "3", "dataMaxima": "08/09/2026", "coErro": "0"}])

        with patch("nanostore.correios.urlopen", side_effect=fake_urlopen):
            result = self.make_client().estimate_delivery("01001-000", reference_date=date(2026, 9, 2))

        self.assertEqual(2, len(calls))
        self.assertIn("prazo/v1/nacional/SERVICO1", calls[1][0].full_url)
        self.assertIn("cepOrigem=80000000", calls[1][0].full_url)
        self.assertIn("cepDestino=01001000", calls[1][0].full_url)
        self.assertEqual(3, result["business_days"])
        self.assertEqual("2026-09-08", result["estimated_delivery_date"])

    def test_parses_tracking_events(self):
        responses = [
            FakeResponse({"token": "TOKEN", "expiraEm": "2099-01-01T00:00:00Z"}),
            FakeResponse({"objetos": [{"eventos": [{
                "codigo": "BDE",
                "descricao": "Objeto entregue ao destinatario",
                "dtHrCriado": "2026-09-05T14:30:00-03:00",
                "unidade": {"nome": "Unidade de Distribuicao", "endereco": {"cidade": "Curitiba", "uf": "PR"}},
            }]}]}),
        ]
        with patch("nanostore.correios.urlopen", side_effect=responses):
            result = self.make_client().track("aa123456789br")
        self.assertEqual("AA123456789BR", result["tracking_code"])
        self.assertEqual("BDE", result["events"][0]["code"])
        self.assertIn("Curitiba", result["events"][0]["location"])
        self.assertTrue(result["events"][0]["occurred_at"].endswith("Z"))

    def test_deadline_fallback_counts_weekdays_when_api_omits_maximum_date(self):
        responses = [
            FakeResponse({"token": "TOKEN", "expiraEm": "2099-01-01T00:00:00Z"}),
            FakeResponse([{"prazoEntrega": "3", "coErro": "0"}]),
        ]
        with patch("nanostore.correios.urlopen", side_effect=responses):
            result = self.make_client().estimate_delivery("01001000", reference_date=date(2026, 9, 4))
        self.assertEqual("2026-09-09", result["estimated_delivery_date"])

    def test_unconfigured_client_refuses_to_invent_deadline(self):
        with self.assertRaises(CorreiosError):
            CorreiosClient({}).estimate_delivery("01001000", "SERVICO")


if __name__ == "__main__":
    unittest.main()
