import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ControleVozGlobalTests(unittest.TestCase):
    def test_header_exposes_global_voice_control_and_confirmation(self):
        html = (ROOT / "RioBranco.html").read_text(encoding="utf-8")

        self.assertIn('id="voiceControlBtn"', html)
        self.assertIn('onclick="voiceControlToggle()"', html)
        self.assertIn('id="voiceControlPanel"', html)
        self.assertIn('id="voiceControlConfirmBtn"', html)
        self.assertIn('aria-live="polite"', html)

    def test_router_supports_navigation_fields_buttons_and_agent_fallback(self):
        script = (ROOT / "script.js").read_text(encoding="utf-8")

        self.assertIn('document.querySelectorAll(".menu-item, .submenu-item")', script)
        self.assertIn('element.classList?.contains("submenu-item")', script)
        self.assertIn("wantedCoverage * 500", script)
        self.assertIn('input:not([type=\'hidden\']):not([type=\'file\']), textarea, select', script)
        self.assertIn('document.querySelectorAll("button, a, [role=\'button\']', script)
        self.assertIn("voiceControlSetField(fill[1], fill[2])", script)
        self.assertIn('row.closest("table")?.querySelectorAll("thead th")', script)
        self.assertIn("element.getClientRects().length === 0", script)
        self.assertIn("voiceControlOpenAgent(command)", script)
        self.assertNotIn("eval(", script)

    def test_mutating_actions_require_expiring_confirmation(self):
        script = (ROOT / "script.js").read_text(encoding="utf-8")

        self.assertIn("voiceControlNeedsConfirmation", script)
        self.assertIn("voiceControlQueueConfirmation", script)
        self.assertIn("Date.now() + 30000", script)
        self.assertIn("voiceControlConfirmPending", script)
        self.assertIn("voiceControlCancelPending", script)

    def test_recognition_uses_brazilian_portuguese(self):
        script = (ROOT / "script.js").read_text(encoding="utf-8")

        self.assertGreaterEqual(script.count('recognition.lang = "pt-BR"'), 2)


if __name__ == "__main__":
    unittest.main()
