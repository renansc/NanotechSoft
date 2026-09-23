import unittest
from pathlib import Path

from gestao_processos_compras import (
    ensure_minimum_stock_purchase,
    minimum_stock_purchase_quantity,
)


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []
        self.lastrowid = 321

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


def product_row():
    return {
        "id": 9,
        "nome_produto": "Acucar",
        "produto_base_nome": "",
        "grupo_estoque": "MATERIA_PRIMA",
        "unidade": "SC",
        "embalagem_tipo_padrao": "SC",
        "estoque_minimo": 100,
    }


class EstoqueMinimoComprasTests(unittest.TestCase):
    def test_dispara_no_minimo_e_respeita_lote_e_multiplo(self):
        self.assertEqual(0, minimum_stock_purchase_quantity(101, 100, 0, 12))
        self.assertEqual(12, minimum_stock_purchase_quantity(100, 100, 0, 12))
        self.assertEqual(36, minimum_stock_purchase_quantity(70, 100, 0, 12))
        self.assertEqual(48, minimum_stock_purchase_quantity(70, 100, 40, 12))

    def test_cria_compra_auditavel(self):
        cur = FakeCursor([
            product_row(),
            {"estoque_area": "PRODUCAO", "estoque_subgrupo": "MATERIA_PRIMA"},
            None,
            {"fornecedor_id": 7, "prazo_entrega_dias": 5, "lote_minimo": 40, "multiplo_compra": 10},
        ])
        result = ensure_minimum_stock_purchase(cur, 9, 80, actor="operador")
        self.assertTrue(result["created"])
        self.assertEqual(40, result["quantidade"])
        self.assertEqual(321, result["id"])
        sql = "\n".join(query for query, _params in cur.executed)
        self.assertIn("INSERT INTO compras_solicitacoes", sql)
        self.assertIn("criado_automaticamente", sql)

    def test_nao_duplica_compra_aberta(self):
        cur = FakeCursor([
            product_row(),
            {"estoque_area": "PRODUCAO", "estoque_subgrupo": "MATERIA_PRIMA"},
            {"id": 88, "status": "cotacao"},
        ])
        result = ensure_minimum_stock_purchase(cur, 9, 50, actor="operador")
        self.assertFalse(result["created"])
        self.assertEqual("compra_aberta", result["reason"])
        self.assertEqual(88, result["id"])
        self.assertFalse(any("INSERT INTO compras_solicitacoes" in query for query, _params in cur.executed))

    def test_produto_acabado_continua_no_planejamento_de_producao(self):
        cur = FakeCursor([
            product_row(),
            {"estoque_area": "PRODUCAO", "estoque_subgrupo": "PRODUTOS"},
        ])
        result = ensure_minimum_stock_purchase(cur, 9, 50, actor="operador")
        self.assertEqual("produto_acabado", result["reason"])
        self.assertFalse(any("INSERT INTO compras_solicitacoes" in query for query, _params in cur.executed))

    def test_campo_aparece_no_cadastro_e_na_posicao(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "RioBranco.html").read_text(encoding="utf-8")
        script = (root / "script.js").read_text(encoding="utf-8")
        source = (root / "server.py").read_text(encoding="utf-8")
        self.assertIn('id="estoqueCadastroMinimo"', html)
        self.assertIn("Estoque Min.", html)
        self.assertIn("estoque_minimo DECIMAL(14,3)", source)
        self.assertIn("avaliar_estoque_minimo", script)
        self.assertIn("_avaliar_estoque_minimo_produtos", source)


if __name__ == "__main__":
    unittest.main()
