import json
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]

EXPECTED_APPS = [
    ("riob", "RioB"),
    ("financeiro", "Financeiro"),
    ("nanoponto", "Ponto"),
    ("nanostore", "Store"),
    ("automacao", "Automacao"),
    ("zap", "Zap"),
    ("riob-chat", "Chat"),
    ("riob-chat-ia", "Ia-chatbot"),
    ("riob-telefonia", "Telefonia"),
    ("riob-cameras", "Cameras"),
    ("chamados", "Chamados"),
    ("tecnologia", "Tecnologia"),
    ("riob-esxi", "ESXi"),
    ("riob-email", "Email"),
    ("riob-xml", "XML"),
]


class RioBrancoPortalTests(unittest.TestCase):
    def test_deploy_allows_only_the_expected_apps(self):
        allowed = [
            line.strip()
            for line in (PROJECT_DIR / "apps_liberados.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

        self.assertEqual([app_key for app_key, _ in EXPECTED_APPS], allowed)
        self.assertTrue({"gpsmusical", "bpa", "pacs", "tatoo"}.isdisjoint(allowed))

    def test_global_modules_remain_versioned_but_outside_rio_branco_contract(self):
        for app_key in ("gpsmusical", "bpa", "tatoo"):
            with self.subTest(app_key=app_key):
                self.assertTrue((PROJECT_DIR / "apps" / app_key / "app.json").is_file())

        self.assertFalse((PROJECT_DIR / "apps" / "pacs").exists())
        self.assertFalse((PROJECT_DIR / "apps" / "gpsmusical" / "source" / "gps_musical_backup.json").exists())
        compose = (PROJECT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("pacs-postgres:", compose)

    def test_rio_branco_contract_matches_the_deploy(self):
        payload = json.loads((PROJECT_DIR / "clientes-modulos.json").read_text(encoding="utf-8"))
        client = next(item for item in payload["clients"] if item["id"] == "rio-branco")
        contracted = [(item["slug"], item["nome"]) for item in client["modules"]]

        self.assertFalse(client["allModules"])
        self.assertEqual(EXPECTED_APPS, contracted)

    def test_manifest_names_and_order_form_three_rows_of_five(self):
        manifests = []
        for app_key, _ in EXPECTED_APPS:
            manifests.append(
                json.loads((PROJECT_DIR / "apps" / app_key / "app.json").read_text(encoding="utf-8"))
            )
        ordered = sorted(manifests, key=lambda item: (item["ordem"], item["nome"].lower()))

        self.assertEqual(EXPECTED_APPS, [(item["app_key"], item["nome"]) for item in ordered])
        self.assertEqual([10 * index for index in range(1, 16)], [item["ordem"] for item in ordered])
        self.assertEqual(3, len(ordered) // 5)

    def test_desktop_portal_grid_has_five_columns(self):
        css = (PROJECT_DIR / "static/style.css").read_text(encoding="utf-8")

        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr));", css)

    def test_compose_defaults_to_the_rio_branco_contract(self):
        compose = (PROJECT_DIR / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("CLIENTE_DEPLOY_ID: ${CLIENTE_DEPLOY_ID:-rio-branco}", compose)

    def test_compose_allows_enabling_ollama_per_environment(self):
        compose = (PROJECT_DIR / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("RB_AGENT_LLM_PROVIDER: ${RB_AGENT_LLM_PROVIDER:-off}", compose)
        self.assertIn("RB_AGENT_OLLAMA_URL: ${RB_AGENT_OLLAMA_URL:-http://host.docker.internal:11434}", compose)
        self.assertIn("RB_AGENT_OLLAMA_MODEL: ${RB_AGENT_OLLAMA_MODEL:-qwen2.5:3b}", compose)
        self.assertIn("RB_AGENT_LLM_CONTEXT_MODE: ${RB_AGENT_LLM_CONTEXT_MODE:-full}", compose)
        self.assertIn("RB_AGENT_OLLAMA_NUM_CTX: ${RB_AGENT_OLLAMA_NUM_CTX:-8192}", compose)

    def test_user_configuration_uses_the_wide_responsive_layout(self):
        html = (PROJECT_DIR / "templates/config.html").read_text(encoding="utf-8")
        css = (PROJECT_DIR / "static/style.css").read_text(encoding="utf-8")

        self.assertIn('class="user-picker"', html)
        self.assertIn("user-security-grid", html)
        self.assertIn(".config-panel.user-admin-panel", css)
        self.assertIn("max-width: 1100px;", css)
        self.assertIn(".form-grid.user-security-grid", css)
        self.assertIn("grid-template-columns: minmax(280px, 2fr) minmax(200px, 1fr);", css)


if __name__ == "__main__":
    unittest.main()
