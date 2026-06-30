import unittest

from tools.riob_context import build_environment_inventory, build_repo_context, build_repo_manifest, build_system_overview, build_task_brief, format_environment_inventory, format_repo_context, format_repo_manifest, format_repo_sources, format_system_overview, format_task_brief


class RioBrancoContextTests(unittest.TestCase):
    def test_brief_for_nfe_mentions_backend_and_docs(self):
        brief = build_task_brief("corrigir bug da NF-e no backend")
        self.assertEqual(brief["intent"], "debug")
        self.assertIn("server.py", brief["likely_files"])
        self.assertIn("docs/NFE_RECEITA_E_INTEGRACAO.md", brief["likely_files"])
        text = format_task_brief(brief)
        self.assertIn("Fluxo recomendado", text)

    def test_brief_for_deploy_mentions_ops_files(self):
        brief = build_task_brief("melhorar deploy e backup do sistema")
        self.assertEqual(brief["intent"], "ops")
        self.assertIn("tools/riob_agent.py", brief["likely_files"])
        self.assertIn("docs/OPERACAO_E_DEPLOY.md", brief["likely_files"])

    def test_brief_for_frontend_mentions_ui_files(self):
        brief = build_task_brief("ajustar a tela do kanban no frontend")
        self.assertEqual(brief["intent"], "change")
        self.assertIn("RioBranco.html", brief["likely_files"])
        self.assertIn("script.js", brief["likely_files"])

    def test_repo_context_finds_ip_and_cnpj(self):
        context = build_repo_context("qual meu ip interno e o cnpj da empresa")
        text = format_repo_context(context)
        sources = format_repo_sources(context)
        self.assertIn("RB_PUBLIC_BASE_URL", text)
        self.assertIn("20.984.401/0001-30", text)
        self.assertIn("Fontes:", sources)
        self.assertTrue(".env" in sources or "docker-compose.yml" in sources)

    def test_repo_context_finds_storage_paths(self):
        context = build_repo_context("onde ficam as fotos de devolucao e os anexos")
        text = format_repo_context(context)
        sources = format_repo_sources(context)
        self.assertIn("FotosDevolucoes", text)
        self.assertIn("ChatAnexos", text)
        self.assertIn("Fontes:", sources)
        self.assertTrue("server.py" in sources or "docker-compose.yml" in sources)

    def test_system_overview_covers_core_modules(self):
        overview = build_system_overview()
        text = format_system_overview(overview)
        self.assertIn("Fretes e kanban", text)
        self.assertIn("Estoque e NF-e", text)
        self.assertIn("Chat e I.A-Rio", text)

    def test_repo_manifest_includes_core_sources(self):
        manifest = build_repo_manifest()
        text = format_repo_manifest(manifest)
        self.assertIn("Mapa do repositorio", text)
        self.assertIn("server.py", text)
        self.assertIn("docs/AI_CONTEXT.md", text)

    def test_environment_inventory_includes_runtime_and_compose(self):
        inventory = build_environment_inventory()
        text = format_environment_inventory(inventory)
        self.assertIn("Ambiente de runtime", text)
        self.assertIn("Servicos do docker-compose", text)
        self.assertIn("Diretorios operacionais presentes", text)


if __name__ == "__main__":
    unittest.main()
