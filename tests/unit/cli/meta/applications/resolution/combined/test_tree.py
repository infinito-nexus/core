# tests/unit/cli/meta/applications/resolution/combined/test_tree.py
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.meta.applications.resolution.combined import repo_paths
from cli.meta.applications.resolution.combined.tree import print_tree


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class TestCombinedTree(unittest.TestCase):
    def test_tree_shows_services_and_cycle_marker(self) -> None:
        """
        Build:
          start(app) run_after -> web-app-keycloak
          start config enables dashboard => web-app-dashboard
          keycloak run_after -> start (cycle)

        Tree should show [services] and a cycle marker.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "roles").mkdir()

            # start app role with dashboard enabled.
            # Per req-008/req-010, meta/services.yml is the services map at the
            # file root, with run_after under the role's primary entity.
            _write(
                root / "roles" / "start" / "vars" / "main.yml",
                "application_id: start\n",
            )
            _write(
                root / "roles" / "start" / "meta" / "services.yml",
                (
                    "start:\n"
                    "  run_after:\n"
                    "    - web-app-keycloak\n"
                    "dashboard:\n"
                    "  enabled: true\n"
                    "  shared: true\n"
                ),
            )

            # keycloak exists, and points back to start to force a visible cycle.
            # Entity name for "web-app-keycloak" is "keycloak".
            _write(
                root / "roles" / "web-app-keycloak" / "vars" / "main.yml",
                "application_id: web-app-keycloak\n",
            )
            _write(
                root / "roles" / "web-app-keycloak" / "meta" / "services.yml",
                "keycloak:\n  run_after:\n    - start\n",
            )

            # required folders exist
            (root / "roles" / "start").mkdir(parents=True, exist_ok=True)
            (root / "roles" / "web-app-keycloak").mkdir(parents=True, exist_ok=True)
            (root / "roles" / "web-app-dashboard").mkdir(parents=True, exist_ok=True)

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    print_tree("start")
                out = buf.getvalue()

            self.assertIn("[services]", out)
            self.assertIn("web-app-dashboard", out)
            self.assertIn("↩︎ (cycle)", out)


if __name__ == "__main__":
    unittest.main()
