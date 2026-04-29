# tests/unit/cli/meta/applications/resolution/combined/test_role_introspection.py
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.meta.applications.resolution.combined import repo_paths
from cli.meta.applications.resolution.combined.errors import CombinedResolutionError
from cli.meta.applications.resolution.combined.role_introspection import (
    has_application_id,
    load_dependencies_app_only,
    load_run_after,
    load_shared_service_roles_for_app,
    require_role_exists,
)


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class TestCombinedRoleIntrospection(unittest.TestCase):
    def test_require_role_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "roles" / "web-app-x").mkdir(parents=True)

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                require_role_exists("web-app-x")
                with self.assertRaises(CombinedResolutionError):
                    require_role_exists("missing-role")

    def test_has_application_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "roles" / "a" / "vars" / "main.yml", "application_id: a\n")
            (root / "roles" / "b").mkdir(parents=True)

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                self.assertTrue(has_application_id("a"))
                self.assertFalse(has_application_id("b"))

    def test_load_run_after(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Per req-010 run_after lives under meta/services.yml.<entity>.
            # Entity for plain "a" is "a" itself.
            _write(
                root / "roles" / "a" / "meta" / "services.yml",
                "a:\n  run_after:\n    - web-app-x\n    - web-app-y\n",
            )
            (root / "roles" / "web-app-x").mkdir(parents=True)
            (root / "roles" / "web-app-y").mkdir(parents=True)

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                self.assertEqual(load_run_after("a"), ["web-app-x", "web-app-y"])

    def test_load_dependencies_app_only_filters_non_app_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # start role is app
            _write(
                root / "roles" / "start" / "vars" / "main.yml",
                "application_id: start\n",
            )
            _write(
                root / "roles" / "start" / "meta" / "main.yml",
                "dependencies:\n  - app-dep\n  - non-app-dep\n",
            )
            # app-dep has application_id
            _write(
                root / "roles" / "app-dep" / "vars" / "main.yml",
                "application_id: app-dep\n",
            )
            (root / "roles" / "app-dep").mkdir(parents=True, exist_ok=True)
            # non-app-dep exists but no application_id
            (root / "roles" / "non-app-dep").mkdir(parents=True, exist_ok=True)

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                deps = load_dependencies_app_only("start")
                self.assertEqual(deps, ["app-dep"])

    def test_load_shared_service_roles_for_app_includes_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # wordpress is app
            _write(
                root / "roles" / "web-app-wordpress" / "vars" / "main.yml",
                "application_id: wordpress\n",
            )
            # Per req-008 the file root IS the services map (no
            # `compose.services` envelope).
            _write(
                root / "roles" / "web-app-wordpress" / "meta" / "services.yml",
                "oidc:\n"
                "  enabled: true\n"
                "  shared: true\n"
                "dashboard:\n"
                "  enabled: true\n"
                "  shared: true\n",
            )

            # required provider role folders must exist
            (root / "roles" / "web-app-keycloak").mkdir(parents=True)
            (root / "roles" / "web-app-dashboard").mkdir(parents=True)

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                roles = load_shared_service_roles_for_app("web-app-wordpress")
                self.assertEqual(roles, ["web-app-keycloak", "web-app-dashboard"])


if __name__ == "__main__":
    unittest.main()
