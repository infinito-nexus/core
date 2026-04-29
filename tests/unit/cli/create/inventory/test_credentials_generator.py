# tests/unit/cli/create/inventory/test_credentials_generator.py

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml import YAML

from cli.create.inventory.credentials_generator import generate_credentials_for_roles


class TestCredentialsGenerator(unittest.TestCase):
    def test_generate_credentials_for_roles_merges_snippets(self):
        yaml_rt = YAML(typ="rt")
        yaml_rt.preserve_quotes = True

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            project_root = tmp / "repo"
            project_root.mkdir()

            roles_dir = tmp / "roles"
            roles_dir.mkdir()

            # Create a fake role path that resolver returns
            role_path = roles_dir / "web-app-nextcloud"
            (role_path / "meta").mkdir(parents=True)
            (role_path / "meta" / "schema.yml").write_text("x: 1\n", encoding="utf-8")

            host_vars_file = tmp / "host_vars.yml"
            host_vars_file.write_text("", encoding="utf-8")
            vault_pw_file = tmp / ".password"
            vault_pw_file.write_text("dummy\n", encoding="utf-8")

            snippet = """\
applications:
  web-app-nextcloud:
    credentials:
      admin_password: secret
ansible_become_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
    ENCRYPTEDVALUE
"""

            with (
                patch(
                    "cli.create.inventory.credentials_generator.resolve_role_path",
                    return_value=role_path,
                ),
                patch(
                    "cli.create.inventory.credentials_generator.subprocess.run"
                ) as spr,
            ):
                spr.return_value.returncode = 0
                spr.return_value.stdout = snippet
                spr.return_value.stderr = ""

                generate_credentials_for_roles(
                    application_ids=["web-app-nextcloud"],
                    roles_dir=roles_dir,
                    host_vars_file=host_vars_file,
                    vault_password_file=vault_pw_file,
                    project_root=project_root,
                    env={"PYTHONPATH": "x"},
                    workers=1,
                )

            with host_vars_file.open("r", encoding="utf-8") as f:
                doc = yaml_rt.load(f) or {}

            self.assertIn("applications", doc)
            self.assertEqual(
                doc["applications"]["web-app-nextcloud"]["credentials"][
                    "admin_password"
                ],
                "secret",
            )
            self.assertEqual(
                getattr(doc["ansible_become_password"], "tag", None), "!vault"
            )

    def test_generate_credentials_does_not_fail_for_roles_without_schema(self):
        """
        New behavior: schema-less roles may still be passed to cli.create.credentials
        because credentials generation can be driven transitively from config/main.yml.
        The generator must not crash if the snippet is empty.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            roles_dir = tmp / "roles"
            roles_dir.mkdir()

            role_path = roles_dir / "web-app-noschema"
            role_path.mkdir()

            host_vars_file = tmp / "host_vars.yml"
            host_vars_file.write_text("", encoding="utf-8")
            vault_pw_file = tmp / ".password"
            vault_pw_file.write_text("dummy\n", encoding="utf-8")

            with (
                patch(
                    "cli.create.inventory.credentials_generator.resolve_role_path",
                    return_value=role_path,
                ),
                patch(
                    "cli.create.inventory.credentials_generator.subprocess.run"
                ) as spr,
            ):
                # Simulate: credentials tool runs fine but outputs nothing
                spr.return_value.returncode = 0
                spr.return_value.stdout = ""
                spr.return_value.stderr = ""

                generate_credentials_for_roles(
                    application_ids=["web-app-noschema"],
                    roles_dir=roles_dir,
                    host_vars_file=host_vars_file,
                    vault_password_file=vault_pw_file,
                    project_root=tmp,
                    env=None,
                    workers=1,
                )

            # Should not crash and may or may not call subprocess depending on resolver behavior.
            # With our patch, it SHOULD call it exactly once.
            spr.assert_called_once()

    def test_generate_credentials_replaces_empty_existing_value(self):
        yaml_rt = YAML(typ="rt")
        yaml_rt.preserve_quotes = True

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            project_root = tmp / "repo"
            project_root.mkdir()

            roles_dir = tmp / "roles"
            roles_dir.mkdir()

            role_path = roles_dir / "web-app-taiga"
            (role_path / "meta").mkdir(parents=True)
            (role_path / "meta" / "schema.yml").write_text("x: 1\n", encoding="utf-8")

            host_vars_file = tmp / "host_vars.yml"
            host_vars_file.write_text(
                "applications:\n"
                "  web-app-taiga:\n"
                "    credentials:\n"
                '      oauth2_proxy_cookie_secret: ""\n',
                encoding="utf-8",
            )
            vault_pw_file = tmp / ".password"
            vault_pw_file.write_text("dummy\n", encoding="utf-8")

            snippet = """\
applications:
  web-app-taiga:
    credentials:
      oauth2_proxy_cookie_secret: regenerated-secret
"""

            with (
                patch(
                    "cli.create.inventory.credentials_generator.resolve_role_path",
                    return_value=role_path,
                ),
                patch(
                    "cli.create.inventory.credentials_generator.subprocess.run"
                ) as spr,
            ):
                spr.return_value.returncode = 0
                spr.return_value.stdout = snippet
                spr.return_value.stderr = ""

                generate_credentials_for_roles(
                    application_ids=["web-app-taiga"],
                    roles_dir=roles_dir,
                    host_vars_file=host_vars_file,
                    vault_password_file=vault_pw_file,
                    project_root=project_root,
                    env={"PYTHONPATH": "x"},
                    workers=1,
                )

            with host_vars_file.open("r", encoding="utf-8") as f:
                doc = yaml_rt.load(f) or {}

            self.assertEqual(
                doc["applications"]["web-app-taiga"]["credentials"][
                    "oauth2_proxy_cookie_secret"
                ],
                "regenerated-secret",
            )
