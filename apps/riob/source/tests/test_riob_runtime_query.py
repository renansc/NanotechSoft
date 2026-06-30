import unittest

import tools.riob_runtime_query as runtime_query


class RioBRuntimeQueryTests(unittest.TestCase):
    def test_parse_frete_message_extracts_city_and_deliveries(self):
        filters = runtime_query.parse_frete_message(
            "qual caminhao vai para londrina com 48 entregas"
        )

        self.assertEqual(filters["city"], "londrina")
        self.assertEqual(filters["deliveries"], 48)
        self.assertEqual(filters["vehicle"], "")

    def test_build_no_match_diagnostic_lists_partial_candidates(self):
        cards = [
            {
                "id": 58,
                "vehicle": "13",
                "plate": "AIM-3J33",
                "load": "Nova Londrina",
                "city": "",
                "route": "",
                "cities": "",
                "deliveries": 58,
                "status": "retornando",
                "status_label": "Retornando",
                "raw": {
                    "cidade": "",
                    "carga_cidade": "",
                    "carga_rota": "",
                },
            },
            {
                "id": 110,
                "vehicle": "14",
                "plate": "AIQ-6237",
                "load": "Arapongas",
                "city": "",
                "route": "",
                "cities": "",
                "deliveries": 48,
                "status": "carregado",
                "status_label": "Carregado Liberado P Viajem",
                "raw": {
                    "cidade": "",
                    "carga_cidade": "",
                    "carga_rota": "",
                },
            },
            {
                "id": 134,
                "vehicle": "",
                "plate": "",
                "load": "Nova Londrina - 20",
                "city": "Nova Londrina",
                "route": "20",
                "cities": "Nova Londrina",
                "deliveries": 2,
                "status": "liberado",
                "status_label": "Liberado para Carregar",
                "raw": {
                    "cidade": "Nova Londrina",
                    "carga_cidade": "Nova Londrina",
                    "carga_rota": "20",
                },
            },
        ]

        diagnostic = runtime_query.build_no_match_diagnostic(
            cards,
            city="londrina",
            deliveries=48,
        )

        self.assertIn("Nenhum frete encontrado com cidade 'londrina' e 48 entregas.", diagnostic)
        self.assertIn("Candidatos por cidade:", diagnostic)
        self.assertIn("Frete #134", diagnostic)
        self.assertIn("Frete #58", diagnostic)
        self.assertIn("Candidatos com 48 entregas:", diagnostic)
        self.assertIn("Frete #110", diagnostic)


if __name__ == "__main__":
    unittest.main()
