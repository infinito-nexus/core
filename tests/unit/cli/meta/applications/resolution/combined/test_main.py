# tests/unit/cli/meta/applications/resolution/combined/test_main.py
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.meta.applications.resolution.combined import repo_paths
from cli.meta.applications.resolution.combined import __main__ as combined_main


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


def _write_meta_services_run_after(
    root: Path, role: str, *, run_after: list[str]
) -> None:
    """Write meta/services.yml with the role's primary entity and run_after."""
    import yaml

    p = root / "roles" / role / "meta" / "services.yml"
    p.parent.mkdir(parents=True, exist_ok=True)
    # For role names without a known category prefix, get_entity_name returns
    # the role name itself.
    p.write_text(yaml.safe_dump({role: {"run_after": run_after}}), encoding="utf-8")


class TestCombinedMain(unittest.TestCase):
    def test_main_list_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_role(root, "app", app_id="app")
            _mk_role(root, "ra1", app_id="ra1")
            _write_meta_services_run_after(root, "app", run_after=["ra1"])

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    with patch("sys.argv", ["prog", "app"]):
                        combined_main.main()
                out = buf.getvalue().strip()
                self.assertEqual(out, "ra1")

    def test_main_tree_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_role(root, "app", app_id="app")
            _mk_role(root, "ra1", app_id="ra1")
            _write_meta_services_run_after(root, "app", run_after=["ra1"])

            with patch.object(repo_paths, "repo_root_from_here", return_value=root):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    with patch("sys.argv", ["prog", "app", "--tree"]):
                        combined_main.main()
                s = buf.getvalue()
                self.assertIn("app", s)
                self.assertIn("[run_after]", s)
                self.assertIn("ra1", s)
