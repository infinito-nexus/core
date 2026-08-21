from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.meta.roles.applications.resolution.affected import __main__ as affected_main
from cli.meta.roles.applications.resolution.combined import repo_paths
from utils.cache.yaml import dump_yaml
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)


def _mk_app_role(root: Path, role: str, app_id: str) -> None:
    role_dir = root / "roles" / role
    (role_dir / "meta").mkdir(parents=True, exist_ok=True)
    (role_dir / "vars").mkdir(parents=True, exist_ok=True)
    (role_dir / ROLE_FILE_VARS_MAIN).write_text(
        f"application_id: {app_id}\n", encoding="utf-8"
    )


def _mk_non_app_role(root: Path, role: str) -> None:
    """Create a role folder without ``application_id``."""
    (root / "roles" / role / "meta").mkdir(parents=True, exist_ok=True)


def _write_run_after(root: Path, role: str, run_after: list[str]) -> None:
    dump_yaml(
        root / "roles" / role / ROLE_FILE_META_SERVICES,
        {role: {"run_after": run_after}},
    )


def _write_dependencies(root: Path, role: str, deps: list[str]) -> None:
    dump_yaml(
        root / "roles" / role / ROLE_FILE_META_MAIN,
        {"dependencies": deps},
    )


class TestAffected(unittest.TestCase):
    def test_seed_only_when_no_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_app_role(root, "leaf", "leaf")
            _mk_app_role(root, "other", "other")

            with patch.object(repo_paths, "PROJECT_ROOT", root):
                self.assertEqual(
                    affected_main.affected_roles(["leaf"]),
                    ["leaf"],
                )

    def test_run_after_consumer_is_included(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_app_role(root, "leaf", "leaf")
            _mk_app_role(root, "consumer", "consumer")
            _write_run_after(root, "consumer", ["leaf"])

            with patch.object(repo_paths, "PROJECT_ROOT", root):
                self.assertEqual(
                    affected_main.affected_roles(["leaf"]),
                    ["consumer", "leaf"],
                )

    def test_dependencies_consumer_is_included_transitively(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_app_role(root, "leaf", "leaf")
            _mk_app_role(root, "mid", "mid")
            _mk_app_role(root, "top", "top")
            _write_dependencies(root, "mid", ["leaf"])
            _write_dependencies(root, "top", ["mid"])

            with patch.object(repo_paths, "PROJECT_ROOT", root):
                self.assertEqual(
                    affected_main.affected_roles(["leaf"]),
                    ["leaf", "mid", "top"],
                )

    def test_shared_service_consumer_is_included(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_app_role(root, "web-app-keycloak", "keycloak")
            _mk_app_role(root, "web-app-consumer", "consumer")
            dump_yaml(
                root / "roles" / "web-app-consumer" / ROLE_FILE_META_SERVICES,
                {
                    "consumer": {},
                    "sso": {"enabled": True, "shared": True, "flavor": "oidc"},
                },
            )

            with patch.object(repo_paths, "PROJECT_ROOT", root):
                got = affected_main.affected_roles(["web-app-keycloak"])
                self.assertIn("web-app-keycloak", got)
                self.assertIn("web-app-consumer", got)

    def test_unknown_role_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_app_role(root, "leaf", "leaf")
            with (
                patch.object(repo_paths, "PROJECT_ROOT", root),
                self.assertRaises(SystemExit),
            ):
                affected_main.affected_roles(["does-not-exist"])

    def test_non_modellable_seed_exits_with_sentinel_code(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_non_app_role(root, "sys-helper")
            _mk_app_role(root, "consumer", "consumer")

            with patch.object(repo_paths, "PROJECT_ROOT", root):
                with self.assertRaises(SystemExit) as ctx:
                    affected_main.affected_roles(["sys-helper"])
                self.assertEqual(
                    ctx.exception.code,
                    affected_main.EXIT_NON_MODELLABLE_SEED,
                )

    def test_non_app_seed_reachable_via_run_after_is_modellable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_non_app_role(root, "sys-helper")
            _mk_app_role(root, "consumer", "consumer")
            _write_run_after(root, "consumer", ["sys-helper"])

            with patch.object(repo_paths, "PROJECT_ROOT", root):
                got = affected_main.affected_roles(["sys-helper"])
            self.assertIn("sys-helper", got)
            self.assertIn("consumer", got)

    def test_main_prints_space_separated_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mk_app_role(root, "leaf", "leaf")
            _mk_app_role(root, "consumer", "consumer")
            _write_run_after(root, "consumer", ["leaf"])

            with patch.object(repo_paths, "PROJECT_ROOT", root):
                buf = io.StringIO()
                with (
                    redirect_stdout(buf),
                    patch(
                        "sys.argv",
                        ["prog", "--changed-roles", "leaf"],
                    ),
                ):
                    affected_main.main()
                self.assertEqual(buf.getvalue().strip(), "consumer leaf")


if __name__ == "__main__":
    unittest.main()
