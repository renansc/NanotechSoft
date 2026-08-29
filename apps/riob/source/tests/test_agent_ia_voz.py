import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentIaVozTests(unittest.TestCase):
    def test_tela_expoe_microfone_e_status_acessivel(self):
        html = (ROOT / "RioBranco.html").read_text(encoding="utf-8")

        self.assertIn('id="agentIaVoiceBtn"', html)
        self.assertIn('onclick="agentIaToggleVoz()"', html)
        self.assertIn('id="agentIaVoiceStatus"', html)
        self.assertIn('aria-live="polite"', html)

    def test_frontend_reconhece_portugues_e_exige_revisao_antes_do_envio(self):
        script = (ROOT / "script.js").read_text(encoding="utf-8")

        self.assertIn("window.webkitSpeechRecognition", script)
        self.assertIn('recognition.lang = "pt-BR"', script)
        self.assertIn("Confira o texto e clique em Enviar", script)
        self.assertNotIn("agentIaEnviarPergunta({", script)


if __name__ == "__main__":
    unittest.main()
