import unittest

import server


class FreteXmlViagemTests(unittest.TestCase):
    def test_allows_compatible_freight_cards_to_be_merged(self):
        origem = {"id": 361, "data_carga": "2026-08-04", "status": "liberado", "veiculo_id": 14, "carga_id": None, "arquivado": False}
        destino = {"id": 360, "data_carga": "2026-08-04", "status": "liberado", "veiculo_id": 14, "carga_id": None, "arquivado": False}

        self.assertEqual("", server._erro_unificacao_fretes(origem, destino))

    def test_blocks_merge_between_different_trucks_or_columns(self):
        origem = {"id": 361, "data_carga": "2026-08-04", "status": "liberado", "veiculo_id": 14, "arquivado": False}

        self.assertIn("mesma coluna", server._erro_unificacao_fretes(origem, {**origem, "id": 360, "status": "carregando"}))
        self.assertIn("veiculos diferentes", server._erro_unificacao_fretes(origem, {**origem, "id": 360, "veiculo_id": 29}))

    def test_grouped_freight_cities_are_normalized_and_deduplicated(self):
        cidades = server._frete_cidades_lista(
            "Londrina - Cambé",
            ["CAMBE", "Rolândia"],
        )

        self.assertEqual(["Londrina", "Cambé", "Rolândia"], cidades)

    def test_uses_vehicle_km_when_trip_has_no_km(self):
        resumo = server._resolver_resumo_viagem_frete(0, 184331, 0, 3)

        self.assertEqual(184331, resumo["km_atual"])
        self.assertEqual(0, resumo["peso"])
        self.assertEqual(3, resumo["qtd_entregas"])

    def test_preserves_existing_trip_values_when_they_are_greater(self):
        resumo = server._resolver_resumo_viagem_frete(184500, 184331, 7, 3)

        self.assertEqual(184500, resumo["km_atual"])
        self.assertEqual(7, resumo["qtd_entregas"])

    def test_never_replaces_trip_km_with_zero(self):
        resumo = server._resolver_resumo_viagem_frete(185000, 0, 1, 1)

        self.assertEqual(185000, resumo["km_atual"])

    def test_uses_weight_and_deliveries_from_linked_load(self):
        resumo = server._resolver_resumo_viagem_frete(
            0,
            184331,
            0,
            1,
            peso_carga=12450.75,
            entregas_carga=18,
        )

        self.assertEqual(12450.75, resumo["peso"])
        self.assertEqual(18, resumo["qtd_entregas"])

    def test_serialized_trip_uses_linked_vehicle_km_as_fallback(self):
        frete = server._serialize_frete_row(
            {
                "id": 572629,
                "nome": "NF-e 572629 - Vincular veiculo",
                "status": "liberado",
                "veiculo_id_resolvido": 54,
                "veiculo_nome_resolvido": "54",
                "km_atual": 0,
                "veiculo_km_atual_resolvido": 184331,
                "peso": 0,
                "carga_peso_total": 12450.75,
                "qtd_entregas": 0,
                "carga_numero_entregas": 18,
                "xml_entregas_total": 1,
            }
        )

        self.assertEqual(54, frete["veiculo_id"])
        self.assertEqual(184331, frete["km_atual"])
        self.assertEqual(12450.75, frete["peso"])
        self.assertEqual(18, frete["qtd_entregas"])


if __name__ == "__main__":
    unittest.main()
