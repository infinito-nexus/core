import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.inventory.provision.role_resolver import resolve_role_path


class _Result:
    def __init__(self, stdout: str):
        self.stdout = stdout


class TestRoleResolver(unittest.TestCase):
    def test_resolve_role_path_prefers_roles_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            roles_dir = tmp / "roles"
            roles_dir.mkdir()
            (roles_dir / "web-app-nextcloud").mkdir()

            with patch(
                "cli.administration.inventory.provision.role_resolver.run_subprocess",
                return_value=_Result("web-app-nextcloud\n"),
            ) as rs:
                p = resolve_role_path(
                    application_id="nextcloud",
                    roles_dir=roles_dir,
                    project_root=tmp,
                    env={"PYTHONPATH": "x"},
                )

            self.assertEqual(p, roles_dir / "web-app-nextcloud")
            cmd = rs.call_args[0][0]
            self.assertIn("-m", cmd)
            self.assertIn("cli.meta.roles.applications.role_name", cmd)

    def test_resolve_role_path_falls_back_to_project_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            roles_dir = tmp / "roles"
            roles_dir.mkdir()

            (tmp / "roles" / "web-app-matomo").mkdir(parents=True)

            with patch(
                "cli.administration.inventory.provision.role_resolver.run_subprocess",
                return_value=_Result("roles/web-app-matomo\n"),
            ):
                p = resolve_role_path(
                    application_id="matomo",
                    roles_dir=roles_dir,
                    project_root=tmp,
                    env=None,
                )

            self.assertEqual(p, tmp / "roles" / "web-app-matomo")

    def test_resolve_role_path_returns_none_on_empty_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            roles_dir = tmp / "roles"
            roles_dir.mkdir()

            with patch(
                "cli.administration.inventory.provision.role_resolver.run_subprocess",
                return_value=_Result("\n"),
            ):
                p = resolve_role_path("x", roles_dir, tmp, env=None)

            self.assertIsNone(p)
