import unittest

import server


class EstoqueTaxonomiaBebidasTests(unittest.TestCase):
    def test_normaliza_sabor_volume_e_apresentacao(self):
        self.assertEqual(
            "UVA 2L",
            server._estoque_base_nome_inferido("Refrigerante Uva PET 2 L"),
        )
        self.assertEqual(
            "LIMAO (SODA) 600ML",
            server._estoque_base_nome_inferido("Soda limão PET 600 ml"),
        )
        self.assertEqual(
            "RETORNAVEL LARANJA 200ML",
            server._estoque_base_nome_inferido(
                "Garrafa retornável Laranja 200 ml",
            ),
        )
        self.assertEqual(
            "AGUA SEM GAS 510ML",
            server._estoque_base_nome_inferido("Água sem gás 510 ml"),
        )

    def test_nome_canonico_prevalece_sobre_cadastro_duplicado(self):
        self.assertEqual(
            "COLA 2L",
            server._estoque_base_nome_inferido(
                "Refrigerante Cola PET 2L",
                grupo_estoque="PET",
                produto_base_nome="REFRI COLA DO CADASTRO ANTIGO",
            ),
        )

    def test_fatores_padrao_das_embalagens(self):
        self.assertEqual(
            6,
            server._fator_base_produto("Uva PET 2L", "PCT", "PCT", "PET"),
        )
        self.assertEqual(
            12,
            server._fator_base_produto("Uva PET 600ML", "PCT", "PCT", "PET"),
        )
        self.assertEqual(
            24,
            server._fator_base_produto(
                "Uva retornável 600ML", "CX", "CX", "GFA",
            ),
        )
        self.assertEqual(
            48,
            server._fator_base_produto(
                "Uva retornável 200ML", "CX", "CX", "GFA",
            ),
        )
        self.assertEqual(
            12,
            server._fator_base_produto(
                "Água com gás 510ML", "PCT", "PCT", "AGUA",
            ),
        )

    def test_classifica_hierarquia_operacional_do_estoque(self):
        self.assertEqual(
            {
                "estoque_area": "PRODUCAO",
                "estoque_subgrupo": "PRODUTOS",
                "exibir_dashboard": True,
            },
            server._estoque_classificacao_operacional(
                {"nome_produto": "Refrigerante Cola PET 2L", "grupo_estoque": "PET"}
            ),
        )
        self.assertEqual(
            "MATERIA_PRIMA",
            server._estoque_classificacao_operacional(
                {
                    "nome_produto": "Concentrado de guaraná",
                    "fornecedor_categorias": ["materia_prima"],
                }
            )["estoque_subgrupo"],
        )
        self.assertEqual(
            "ALMOXARIFADO_GERAL",
            server._estoque_classificacao_operacional(
                {"nome_produto": "Papel A4"}
            )["estoque_area"],
        )


if __name__ == "__main__":
    unittest.main()
