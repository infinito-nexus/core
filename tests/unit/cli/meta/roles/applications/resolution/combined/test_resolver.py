# tests/unit/cli/meta/roles/applications/resolution/combined/test_tree.py
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.meta.roles.applications.resolution.combined import repo_paths
from cli.meta.roles.applications.resolution.combined.resolver import CombinedResolver
from cli.meta.roles.applications.resolution.combined.tree import print_tree
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN


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

            _write(
                root / "roles" / "start" / ROLE_FILE_VARS_MAIN,
                "application_id: start\n",
            )
            _write(
                root / "roles" / "start" / ROLE_FILE_META_SERVICES,
                (
                    "start:\n"
                    "  run_after:\n"
                    "    - web-app-keycloak\n"
                    "dashboard:\n"
                    "  enabled: true\n"
                    "  shared: true\n"
                ),
            )

            _write(
                root / "roles" / "web-app-keycloak" / ROLE_FILE_META_SERVICES,
                "keycloak:\n  run_after:\n    - start\n",
            )

            (root / "roles" / "start").mkdir(parents=True, exist_ok=True)
            (root / "roles" / "web-app-keycloak").mkdir(parents=True, exist_ok=True)
            (root / "roles" / "web-app-dashboard").mkdir(parents=True, exist_ok=True)

            with patch.object(repo_paths, "PROJECT_ROOT", root):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    print_tree("start")
                out = buf.getvalue()

            self.assertIn("[services]", out)
            self.assertIn("web-app-dashboard", out)
            self.assertIn("↩︎ (cycle)", out)


class TestFollowRunAfter(unittest.TestCase):
    def test_run_after_only_role_gated_by_flag(self) -> None:
        """A role reachable ONLY via run_after (no dependency/service edge)
        is included when run_after is followed and excluded when it is not."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "roles").mkdir()
            _write(
                root / "roles" / "start" / ROLE_FILE_VARS_MAIN,
                "application_id: start\n",
            )
            _write(
                root / "roles" / "start" / ROLE_FILE_META_SERVICES,
                "start:\n  run_after:\n    - web-app-extra\n",
            )
            (root / "roles" / "web-app-extra").mkdir(parents=True, exist_ok=True)
            _write(
                root / "roles" / "web-app-extra" / ROLE_FILE_META_SERVICES,
                "extra: {}\n",
            )

            with patch.object(repo_paths, "PROJECT_ROOT", root):
                followed = CombinedResolver(follow_run_after=True).resolve("start")
                gated = CombinedResolver(follow_run_after=False).resolve("start")

        self.assertIn("web-app-extra", followed)
        self.assertNotIn("web-app-extra", gated)


if __name__ == "__main__":
    unittest.main()
