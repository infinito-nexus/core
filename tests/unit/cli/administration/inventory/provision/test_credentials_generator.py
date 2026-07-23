import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml import YAML

from cli.administration.inventory.provision.credentials_generator import (
    generate_credentials_for_roles,
)
from utils.roles.mapping import ROLE_FILE_META_SCHEMA


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
            (role_path / ROLE_FILE_META_SCHEMA).write_text("x: 1\n", encoding="utf-8")

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
                    "cli.administration.inventory.provision.credentials_generator.resolve_role_path",
                    return_value=role_path,
                ),
                patch(
                    "cli.administration.inventory.provision.credentials_generator.subprocess.run"
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
        Schema-less roles may still be passed to cli.administration.inventory.credentials
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
                    "cli.administration.inventory.provision.credentials_generator.resolve_role_path",
                    return_value=role_path,
                ),
                patch(
                    "cli.administration.inventory.provision.credentials_generator.subprocess.run"
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

    def test_generate_credentials_forwards_app_variant_to_subprocess(self):
        """When `app_variants` carries an explicit index for an app, the
        subprocess call to `cli.administration.inventory.credentials` must
        include `--variant <index>` so the variants.yml overlay applies and
        shared-provider discovery sees the variant-merged services map."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            roles_dir = tmp / "roles"
            roles_dir.mkdir()

            role_path = roles_dir / "svc-bkp-volume-2-local"
            (role_path / "meta").mkdir(parents=True)
            (role_path / ROLE_FILE_META_SCHEMA).write_text("x: 1\n", encoding="utf-8")

            host_vars_file = tmp / "host_vars.yml"
            host_vars_file.write_text("", encoding="utf-8")
            vault_pw_file = tmp / ".password"
            vault_pw_file.write_text("dummy\n", encoding="utf-8")

            with (
                patch(
                    "cli.administration.inventory.provision.credentials_generator.resolve_role_path",
                    return_value=role_path,
                ),
                patch(
                    "cli.administration.inventory.provision.credentials_generator.subprocess.run"
                ) as spr,
            ):
                spr.return_value.returncode = 0
                spr.return_value.stdout = ""
                spr.return_value.stderr = ""

                generate_credentials_for_roles(
                    application_ids=["svc-bkp-volume-2-local"],
                    roles_dir=roles_dir,
                    host_vars_file=host_vars_file,
                    vault_password_file=vault_pw_file,
                    project_root=tmp,
                    env=None,
                    workers=1,
                    app_variants={"svc-bkp-volume-2-local": 2},
                )

            spr.assert_called_once()
            cmd = spr.call_args.args[0]
            self.assertIn("--variant", cmd)
            self.assertEqual(cmd[cmd.index("--variant") + 1], "2")

    def test_generate_credentials_omits_variant_arg_when_not_set(self):
        """Apps absent from `app_variants` must not receive a `--variant`
        flag — the credentials CLI then falls back to the role's base
        config (variants.yml overlay is not applied)."""
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
                    "cli.administration.inventory.provision.credentials_generator.resolve_role_path",
                    return_value=role_path,
                ),
                patch(
                    "cli.administration.inventory.provision.credentials_generator.subprocess.run"
                ) as spr,
            ):
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

            spr.assert_called_once()
            cmd = spr.call_args.args[0]
            self.assertNotIn("--variant", cmd)

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
            (role_path / ROLE_FILE_META_SCHEMA).write_text("x: 1\n", encoding="utf-8")

            host_vars_file = tmp / "host_vars.yml"
            host_vars_file.write_text(
                "applications:\n"
                "  web-app-taiga:\n"
                "    credentials:\n"
                '      sso_proxy_cookie_secret: ""\n',
                encoding="utf-8",
            )
            vault_pw_file = tmp / ".password"
            vault_pw_file.write_text("dummy\n", encoding="utf-8")

            snippet = """\
applications:
  web-app-taiga:
    credentials:
      sso_proxy_cookie_secret: regenerated-secret
"""

            with (
                patch(
                    "cli.administration.inventory.provision.credentials_generator.resolve_role_path",
                    return_value=role_path,
                ),
                patch(
                    "cli.administration.inventory.provision.credentials_generator.subprocess.run"
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
                    "sso_proxy_cookie_secret"
                ],
                "regenerated-secret",
            )
