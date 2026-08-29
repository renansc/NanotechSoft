import unittest
from pathlib import Path

from tools import riob_agent


class RioBrancoAgentCliTests(unittest.TestCase):
    def test_project_root_resolution_supports_container_app_path(self):
        self.assertEqual(Path("/app"), riob_agent.resolve_project_root(Path("/app")))

    def test_project_root_resolution_keeps_monorepo_layout(self):
        app_root = Path("/srv/nanotechsoft/apps/riob/source")
        self.assertEqual(Path("/srv/nanotechsoft"), riob_agent.resolve_project_root(app_root))


if __name__ == "__main__":
    unittest.main()
