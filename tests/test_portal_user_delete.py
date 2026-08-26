import importlib.util
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
HAS_FLASK = importlib.util.find_spec("flask") is not None


class PortalUserDeleteTests(unittest.TestCase):
    def test_frontend_oferece_exclusao_e_chama_api_delete(self):
        source = (PROJECT_DIR / "static/app.js").read_text(encoding="utf-8")
        markup = (PROJECT_DIR / "templates/config.html").read_text(encoding="utf-8")

        self.assertIn("data-user-delete", markup)
        self.assertIn('method: "DELETE"', source)
        self.assertIn("Excluir permanentemente o usuario", source)

    def test_backend_impede_autoexclusao_e_exclui_em_transacao(self):
        source = (PROJECT_DIR / "app.py").read_text(encoding="utf-8")

        self.assertIn('methods=["DELETE"]', source)
        self.assertIn("nao pode excluir o proprio usuario", source)
        self.assertIn('cur.execute("DELETE FROM usuarios WHERE id=%s"', source)
        self.assertIn("conn.rollback()", source)


if __name__ == "__main__":
    unittest.main()
