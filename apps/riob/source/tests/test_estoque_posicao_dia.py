import datetime
import unittest
from pathlib import Path

import server


SOURCE_DIR = Path(__file__).resolve().parents[1]


class EstoquePosicaoDiaTests(unittest.TestCase):
    def test_consolida_saldos_e_totais_por_grupo(self):
        produto = {
            "id": 7,
            "codigo_barras": "7890000000001",
            "codigo_produto_nfe": "ACU001",
            "nome_produto": "Acucar",
            "grupo_estoque": "INSUMOS",
            "produto_base_nome": "Acucar",
            "ativo": 1,
        }
        lookup = {
            "_produtos": [produto],
            "codigo_barras": {"7890000000001": produto},
            "codigo_produto_nfe": {"ACU001": produto},
            "nome_produto": {"ACUCAR": produto},
            "produto_base_key": {},
            "codigo_origem": {origem: {} for origem in server._ESTOQUE_CODIGO_ORIGENS},
        }
        movimentos = [{
            "codigo_barras": "7890000000001",
            "codigo_produto_nfe": "ACU001",
            "nome_produto": "Acucar",
            "saldo_inicial": 100,
            "entradas_dia": 30,
            "saidas_dia": 12,
            "saldo_final": 118,
            "movimentacoes_dia": 2,
            "ultima_movimentacao": datetime.datetime(2026, 10, 22, 15, 0),
        }]
        payload = server._montar_relatorio_posicao_estoque_dia(
            movimentos,
            lookup,
            {"INSUMOS": {"codigo": "INSUMOS", "nome": "Insumos", "ordem": 10}},
            datetime.date(2026, 10, 22),
        )

        self.assertEqual(1, payload["resumo"]["grupos"])
        self.assertEqual(100, payload["resumo"]["saldo_inicial"])
        self.assertEqual(30, payload["resumo"]["entradas_dia"])
        self.assertEqual(12, payload["resumo"]["saidas_dia"])
        self.assertEqual(118, payload["resumo"]["saldo_final"])
        self.assertEqual("Insumos", payload["grupos"][0]["nome"])

    def test_filtro_de_grupo(self):
        lookup = {
            "_produtos": [], "codigo_barras": {}, "codigo_produto_nfe": {},
            "nome_produto": {}, "produto_base_key": {},
            "codigo_origem": {origem: {} for origem in server._ESTOQUE_CODIGO_ORIGENS},
        }
        payload = server._montar_relatorio_posicao_estoque_dia(
            [{"nome_produto": "Produto A", "saldo_final": 5}],
            lookup, {}, datetime.date(2026, 10, 22), grupo_estoque="PET",
        )
        self.assertEqual([], payload["rows"])

    def test_nao_mistura_mesmo_nome_em_grupos_ou_produtos_diferentes(self):
        pet = {
            "id": 9, "codigo_produto_nfe": "007000", "nome_produto": "GUARANA PET 6X2L",
            "grupo_estoque": "PET", "produto_base_nome": "GUARANA 2L",
            "embalagem_tipo_padrao": "PCT", "fator_embalagem_padrao": 6, "ativo": 1,
        }
        rotulo = {
            "id": 32, "codigo_produto_nfe": "021981", "nome_produto": "ROTULO GUARANA 2L",
            "grupo_estoque": "OUTROS", "produto_base_nome": "ROTULO GUARANA 2L",
            "embalagem_tipo_padrao": "UN", "fator_embalagem_padrao": 1, "ativo": 1,
        }
        lookup = {
            "_produtos": [pet, rotulo], "codigo_barras": {},
            "codigo_produto_nfe": {"7000": pet, "21981": rotulo},
            "nome_produto": {"GUARANA PET 6X2L": pet, "ROTULO GUARANA 2L": rotulo},
            "produto_base_key": {},
            "codigo_origem": {origem: {} for origem in server._ESTOQUE_CODIGO_ORIGENS},
        }
        payload = server._montar_relatorio_posicao_estoque_dia(
            [
                {"codigo_produto_nfe": "007000", "nome_produto": "GUARANA PET 6X2L", "saldo_final": 47478},
                {"codigo_produto_nfe": "021981", "nome_produto": "ROTULO GUARANA 2L", "saldo_final": 92},
            ],
            lookup,
            {
                "PET": {"nome": "PET", "ordem": 20},
                "OUTROS": {"nome": "Outros", "ordem": 999},
            },
            datetime.date(2026, 10, 22),
        )
        self.assertEqual(2, len(payload["rows"]))
        guarana = next(row for row in payload["rows"] if row["produto_id"] == 9)
        self.assertEqual(47478, guarana["saldo_final"])
        self.assertEqual(6, guarana["pallet_meta"]["unidades_por_volume"])

    def test_consolidacao_canonica_preserva_ids_distintos_de_insumos(self):
        linhas, aliases = {}, {}
        server._estoque_merge_row(linhas, aliases, {
            "produto_id": 164, "nome_produto": "GUARANA 2L", "grupo_estoque": "OUTROS",
            "produto_base_nome": "GUARANA 2L", "codigo_produto_nfe": "000070",
        })
        server._estoque_merge_row(linhas, aliases, {
            "produto_id": 32, "nome_produto": "GUARANA 2L", "grupo_estoque": "OUTROS",
            "produto_base_nome": "ROTULO GUARANA 2L", "codigo_produto_nfe": "021981",
        })
        self.assertEqual(2, len(linhas))
        self.assertIn("ROTULO GUARANA 2L", {row["produto_base_nome"] for row in linhas.values()})

    def test_interface_e_documentacao_expoem_relatorio(self):
        page = (SOURCE_DIR / "RioBranco.html").read_text(encoding="utf-8")
        script = (SOURCE_DIR / "script.js").read_text(encoding="utf-8")
        docs = (SOURCE_DIR / "docs/RELATORIO_POSICAO_ESTOQUE_DIA.md").read_text(encoding="utf-8")
        self.assertIn('data-relatorios-view="estoque_posicao_dia"', page)
        self.assertIn('id="relatorioEstoquePosicaoDiaData"', page)
        self.assertIn("/api/estoque/relatorio-posicao-dia", script)
        self.assertIn("saldo inicial", docs.lower())

    def test_quantidade_logistica_separa_embalagens_e_unidades_soltas(self):
        row = {
            "fator_embalagem_padrao": 12,
            "embalagem_tipo_padrao": "PCT",
            "pallet_meta": {"unidades_por_volume": 12, "rotulo_volume": "pacotes"},
        }
        self.assertEqual(
            "55 pacotes + 5 un. soltas / 665 un.",
            server._estoque_quantidade_logistica_texto(row, 665),
        )
        self.assertEqual(
            "55 pacotes / 660 un.",
            server._estoque_quantidade_logistica_texto(row, 660),
        )

    def test_quantidade_logistica_usa_fator_do_cadastro_quando_meta_nao_identifica(self):
        row = {
            "fator_embalagem_padrao": 12,
            "embalagem_tipo_padrao": "PCT",
            "pallet_meta": {"unidades_por_volume": 0, "rotulo_volume": ""},
        }
        self.assertEqual(
            "1.754 pacotes / 21.048 un.",
            server._estoque_quantidade_logistica_texto(row, 21048),
        )

        script = (SOURCE_DIR / "script.js").read_text(encoding="utf-8")
        self.assertIn('partes.join(" + ")', script)
        self.assertIn("un. soltas", script)


if __name__ == "__main__":
    unittest.main()
