import unittest

import server


class FreteXmlViagemTests(unittest.TestCase):
    def test_allows_compatible_freight_cards_to_be_merged(self):
        origem = {"id": 361, "cidade": "Astorga", "data_carga": "2026-08-04", "status": "liberado", "veiculo_id": 14, "carga_id": 1, "arquivado": False}
        destino = {"id": 360, "cidade": "Londrina", "data_carga": "2026-07-30", "status": "carregando", "veiculo_id": 14, "carga_id": 2, "arquivado": False}

        self.assertEqual("", server._erro_unificacao_fretes(origem, destino))

    def test_blocks_merge_without_the_same_truck(self):
        origem = {"id": 361, "cidade": "Astorga", "data_carga": "2026-08-04", "status": "liberado", "veiculo_id": 14, "arquivado": False}

        self.assertIn("caminhao definido", server._erro_unificacao_fretes(origem, {**origem, "id": 360, "veiculo_id": None}))
        self.assertIn("mesmo caminhao", server._erro_unificacao_fretes(origem, {**origem, "id": 360, "veiculo_id": 29}))

    def test_serialized_freight_exposes_undo_only_for_active_unions(self):
        sem_uniao = server._serialize_frete_row({"id": 10, "unificacoes_ativas": 0})
        com_uniao = server._serialize_frete_row({"id": 11, "unificacoes_ativas": 2})

        self.assertFalse(sem_uniao["pode_desagrupar"])
        self.assertEqual(0, sem_uniao["unificacoes_ativas"])
        self.assertTrue(com_uniao["pode_desagrupar"])
        self.assertEqual(2, com_uniao["unificacoes_ativas"])

    def test_undo_moves_only_the_recorded_links_back_to_the_source(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.rowcount = 0

            def execute(self, sql, params):
                self.calls.append((" ".join(sql.split()), params))
                self.rowcount = len(params) - 2

        cursor = Cursor()
        contagens = server._atualizar_vinculos_desagrupamento(
            cursor,
            {"vendas_diario": [12, 11, 12], "notas_saida": [31]},
            destino_id=200,
            origem_id=100,
        )

        self.assertEqual(2, contagens["vendas_diario"])
        self.assertEqual(1, contagens["notas_saida"])
        self.assertEqual((100, 200, 11, 12), cursor.calls[0][1])
        self.assertEqual((100, 200, 31), cursor.calls[1][1])
        self.assertTrue(all("AND id IN" in sql for sql, _ in cursor.calls))

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
