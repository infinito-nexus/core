import unittest
from unittest.mock import patch


class TestGetDockerPaths(unittest.TestCase):
    def test_get_docker_paths_uses_entity_name_and_builds_layout(self):
        import plugins.filter.get_docker_paths as m

        # After refactor, get_entity_name is used inside utils.docker.paths_utils
        with patch(
            "utils.docker.paths_utils.get_entity_name", lambda app_id: "myentity"
        ):
            out = m.get_docker_paths("web-app-anything", "/opt/compose/")

        self.assertEqual(out["directories"]["instance"], "/opt/compose/myentity/")
        self.assertEqual(out["files"]["env"], "/opt/compose/myentity/.env/env")
        self.assertEqual(out["files"]["compose"], "/opt/compose/myentity/compose.yml")
        self.assertEqual(
            out["files"]["compose_override"],
            "/opt/compose/myentity/compose.override.yml",
        )
        self.assertEqual(
            out["files"]["compose_ca_override"],
            "/opt/compose/myentity/compose.ca.override.yml",
        )
        self.assertEqual(out["files"]["dockerfile"], "/opt/compose/myentity/Dockerfile")

        # Ensure required top-level keys exist
        self.assertIn("directories", out)
        self.assertIn("files", out)


if __name__ == "__main__":
    unittest.main()
