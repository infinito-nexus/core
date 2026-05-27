import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from cli.administration.inventory.provision.host_vars import (
    apply_vars_overrides,
    apply_vars_overrides_from_file,
    ensure_become_password,
    ensure_host_vars_file,
)
from utils.cache.yaml import dump_yaml_str, load_yaml_any


class TestHostVars(unittest.TestCase):
    def test_ensure_host_vars_file_preserves_vault_and_existing_keys(self):
        yaml_rt = YAML(typ="rt")
        yaml_rt.preserve_quotes = True

        with tempfile.TemporaryDirectory() as tmpdir:
            host = "localhost"
            host_vars_file = Path(tmpdir) / f"{host}.yml"

            initial_yaml = """\
secret: !vault |
  $ANSIBLE_VAULT;1.1;AES256
    ENCRYPTEDVALUE
existing_key: foo
"""
            host_vars_file.write_text(initial_yaml, encoding="utf-8")

            ensure_host_vars_file(
                host_vars_file=host_vars_file,
                host=host,
            )

            with host_vars_file.open("r", encoding="utf-8") as f:
                data = yaml_rt.load(f)

            self.assertIsInstance(data, CommentedMap)
            self.assertEqual(data["existing_key"], "foo")
            self.assertEqual(getattr(data["secret"], "tag", None), "!vault")

            # ensure_host_vars_file MUST NOT bake networks/TLS/DOMAIN defaults
            # into host_vars; those live in group_vars / the inventory vars-file
            # so that env-driven values (INFINITO_IP4, INFINITO_DOMAIN, ...)
            # propagate without being silently overridden.
            self.assertNotIn("DOMAIN_PRIMARY", data)
            self.assertNotIn("TLS_ENABLED", data)
            self.assertNotIn("networks", data)

    def test_ensure_host_vars_file_sets_local_connection_for_localhost(self):
        yaml_rt = YAML(typ="rt")
        yaml_rt.preserve_quotes = True

        with tempfile.TemporaryDirectory() as tmpdir:
            host = "localhost"
            host_vars_file = Path(tmpdir) / f"{host}.yml"
            host_vars_file.write_text("", encoding="utf-8")

            ensure_host_vars_file(
                host_vars_file=host_vars_file,
                host=host,
            )

            with host_vars_file.open("r", encoding="utf-8") as f:
                data = yaml_rt.load(f)

            self.assertEqual(data["ansible_connection"], "local")

    def test_apply_vars_overrides_deep_merge_and_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            host_vars_file = Path(tmpdir) / "host_vars.yml"
            host_vars_file.write_text(
                dump_yaml_str(
                    {
                        "networks": {"internet": {"ip4": "1.2.3.4", "ip6": "::1"}},
                        "TLS_ENABLED": True,
                    }
                ),
                encoding="utf-8",
            )

            apply_vars_overrides(
                host_vars_file,
                """
                {
                  "networks": { "internet": { "ip4": "10.0.0.10" } },
                  "TLS_ENABLED": false
                }
                """,
            )

            data = load_yaml_any(host_vars_file)
            self.assertEqual(data["networks"]["internet"]["ip4"], "10.0.0.10")
            self.assertEqual(data["networks"]["internet"]["ip6"], "::1")
            self.assertIs(data["TLS_ENABLED"], False)

    def test_apply_vars_overrides_requires_object(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            host_vars_file = Path(tmpdir) / "host_vars.yml"
            with self.assertRaises(SystemExit):
                apply_vars_overrides(host_vars_file, '["not-an-object"]')

    def test_ensure_become_password_keeps_existing_when_no_cli_password(self):
        yaml_rt = YAML(typ="rt")
        yaml_rt.preserve_quotes = True

        with tempfile.TemporaryDirectory() as tmpdir:
            host_vars_file = Path(tmpdir) / "host.yml"
            vault_pw_file = Path(tmpdir) / ".password"
            vault_pw_file.write_text("dummy\n", encoding="utf-8")

            doc = CommentedMap()
            doc["ansible_become_password"] = "EXISTING_VALUE"
            with host_vars_file.open("w", encoding="utf-8") as f:
                yaml_rt.dump(doc, f)

            ensure_become_password(
                host_vars_file=host_vars_file,
                vault_password_file=vault_pw_file,
                become_password=None,
            )

            with host_vars_file.open("r", encoding="utf-8") as f:
                data = yaml_rt.load(f)

            self.assertEqual(data["ansible_become_password"], "EXISTING_VALUE")

    def test_ensure_become_password_sets_vaulted_value_via_vault_handler(self):
        yaml_rt = YAML(typ="rt")
        yaml_rt.preserve_quotes = True

        with tempfile.TemporaryDirectory() as tmpdir:
            host_vars_file = Path(tmpdir) / "host.yml"
            vault_pw_file = Path(tmpdir) / ".password"
            vault_pw_file.write_text("dummy\n", encoding="utf-8")

            vaulted_snippet = """\
ansible_become_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
    ENCRYPTEDVALUE
"""

            with patch(
                "cli.administration.inventory.provision.host_vars.VaultHandler"
            ) as vh:
                inst = vh.return_value
                inst.encrypt_string.return_value = vaulted_snippet

                ensure_become_password(
                    host_vars_file=host_vars_file,
                    vault_password_file=vault_pw_file,
                    become_password="plain",
                )

            with host_vars_file.open("r", encoding="utf-8") as f:
                data = yaml_rt.load(f)

            node = data["ansible_become_password"]
            self.assertEqual(getattr(node, "tag", None), "!vault")


def test_apply_vars_overrides_from_file_deep_merge_and_overwrite(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        host_vars_file = tmp / "host_vars.yml"
        host_vars_file.write_text(
            dump_yaml_str(
                {
                    "networks": {"internet": {"ip4": "1.2.3.4", "ip6": "::1"}},
                    "TLS_ENABLED": True,
                    "nested": {"keep": "yes"},
                }
            ),
            encoding="utf-8",
        )

        vars_file = tmp / "vars.yml"
        vars_file.write_text(
            dump_yaml_str(
                {
                    "networks": {"internet": {"ip4": "10.0.0.10"}},
                    "TLS_ENABLED": False,
                    "nested": {"newkey": "added"},
                }
            ),
            encoding="utf-8",
        )

        apply_vars_overrides_from_file(
            host_vars_file=host_vars_file, vars_file=vars_file
        )

        data = load_yaml_any(host_vars_file)
        self.assertEqual(data["networks"]["internet"]["ip4"], "10.0.0.10")
        self.assertEqual(data["networks"]["internet"]["ip6"], "::1")
        self.assertIs(data["TLS_ENABLED"], False)
        self.assertEqual(data["nested"]["keep"], "yes")
        self.assertEqual(data["nested"]["newkey"], "added")
