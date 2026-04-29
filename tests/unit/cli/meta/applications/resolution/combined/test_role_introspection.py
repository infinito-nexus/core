from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.meta.applications.resolution.combined.errors import CombinedResolutionError
from cli.meta.applications.resolution.combined import repo_paths
from cli.meta.applications.resolution.combined import role_introspection as ri


def _mk_role(root: Path, role: str, *, app_id: str | None = None) -> None:
    role_dir = root / "roles" / role
    (role_dir / "meta").mkdir(parents=True, exist_ok=True)
    (role_dir / "vars").mkdir(parents=True, exist_ok=True)
    if app_id is not None:
        (role_dir / "vars" / "main.yml").write_text(
            f"application_id: {app_id}\n", encoding="utf-8"
        )


def _write_meta(root: Path, role: str, text: str) -> None:
    p = root / "roles" / role / "meta" / "main.yml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _write_services(root: Path, role: str, text: str) -> None:
    """Write meta/services.yml. The file root IS the services map (req-008)."""
    p = root / "roles" / role / "meta" / "services.yml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class TestRoleIntrospection(unittest.TestCase):
    def test_require_role_exists_ok_and_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_role(root, "web-app-a", app_id="web-app-a")

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                ri.require_role_exists("web-app-a")
                with self.assertRaises(CombinedResolutionError):
                    ri.require_role_exists("missing-role")

    def test_has_application_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_role(root, "web-app-a", app_id="web-app-a")
            _mk_role(root, "sys-helper", app_id=None)

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                self.assertTrue(ri.has_application_id("web-app-a"))
                self.assertFalse(ri.has_application_id("sys-helper"))

    def test_load_run_after_dedup_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_role(root, "web-app-a", app_id="web-app-a")
            _mk_role(root, "dep1", app_id="dep1")
            _mk_role(root, "dep2", app_id="dep2")

            # Per req-010 run_after lives at meta/services.yml.<entity>.run_after
            # Entity name for "web-app-a" is "a".
            _write_services(
                root,
                "web-app-a",
                """
a:
  run_after:
    - dep1
    - dep1
    - dep2
""",
            )

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                ra = ri.load_run_after("web-app-a")
                self.assertEqual(ra, ["dep1", "dep2"])

    def test_load_run_after_invalid_type(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_role(root, "web-app-a", app_id="web-app-a")
            _write_services(
                root,
                "web-app-a",
                """
a:
  run_after: dep1
""",
            )
            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                with self.assertRaises(CombinedResolutionError):
                    ri.load_run_after("web-app-a")

    def test_load_dependencies_app_only_filters_non_app_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_role(root, "web-app-a", app_id="web-app-a")
            _mk_role(root, "web-app-b", app_id="web-app-b")
            _mk_role(root, "sys-helper", app_id=None)

            _write_meta(
                root,
                "web-app-a",
                """
dependencies:
  - web-app-b
  - sys-helper
""",
            )

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                deps = ri.load_dependencies_app_only("web-app-a")
                # sys-helper should be ignored (no application_id)
                self.assertEqual(deps, ["web-app-b"])

    def test_load_dependencies_supports_dict_role_entries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_role(root, "web-app-a", app_id="web-app-a")
            _mk_role(root, "web-app-b", app_id="web-app-b")

            _write_meta(
                root,
                "web-app-a",
                """
dependencies:
  - role: web-app-b
    vars:
      x: 1
""",
            )

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                deps = ri.load_dependencies_app_only("web-app-a")
                self.assertEqual(deps, ["web-app-b"])

    def test_load_dependencies_invalid_entry_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_role(root, "web-app-a", app_id="web-app-a")
            _write_meta(
                root,
                "web-app-a",
                """
dependencies:
  - 123
""",
            )

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                with self.assertRaises(CombinedResolutionError):
                    ri.load_dependencies_app_only("web-app-a")
