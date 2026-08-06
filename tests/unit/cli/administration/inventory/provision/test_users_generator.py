import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from cli.administration.inventory.provision.credentials_generator import (
    generate_credentials_for_roles,
)
from cli.administration.inventory.provision.passwords import generate_user_password
from cli.administration.inventory.provision.users_generator import (
    generate_user_passwords,
    required_usernames,
)
from cli.administration.inventory.validate.users import compare_user_keys
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_USERS

MODULE = "cli.administration.inventory.provision.users_generator"
CREDENTIALS_MODULE = "cli.administration.inventory.provision.credentials_generator"
RUAMEL_MODULE = "cli.administration.inventory.provision.ruamel_io"

REALISTIC_HOST_VARS = """\
---
# Deployment-wide switches. This comment must survive the round trip.
TLS_ENABLED: true

ansible_become_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  36613066303561353835
  3131316536383864370a

applications:
  web-app-a:
    credentials:
      # The role's own generated secret.
      api_key: !vault |
        $ANSIBLE_VAULT;1.1;AES256
        62343439323132313
        6161326533353863
    features:
      matomo: true   # trailing comment
"""

VAULTED = """\
{name}: !vault |
  $ANSIBLE_VAULT;1.1;AES256
    ENCRYPTEDVALUE
"""


def _yaml():
    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True
    return yaml_rt


def _write_role_users(roles_dir: Path, application_id: str, body: str) -> None:
    users_file = roles_dir / application_id / ROLE_FILE_META_USERS
    users_file.parent.mkdir(parents=True, exist_ok=True)
    users_file.write_text(body, encoding="utf-8")


class TestRequiredUsernames(unittest.TestCase):
    def test_only_the_resolved_roles_contribute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = Path(tmpdir)
            _write_role_users(roles_dir, "web-app-a", "alice: {}\n")
            _write_role_users(roles_dir, "web-app-b", "bob: {}\n")

            self.assertEqual(["alice"], required_usernames(roles_dir, ["web-app-a"]))

    def test_a_user_declared_by_two_roles_appears_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = Path(tmpdir)
            _write_role_users(roles_dir, "web-app-a", "administrator: {}\nalice: {}\n")
            _write_role_users(roles_dir, "web-app-b", "administrator: {}\n")

            self.assertEqual(
                ["administrator", "alice"],
                required_usernames(roles_dir, ["web-app-a", "web-app-b"]),
            )

    def test_a_role_without_users_contributes_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = Path(tmpdir)
            _write_role_users(roles_dir, "web-app-a", "alice: {}\n")

            self.assertEqual(
                ["alice"],
                required_usernames(roles_dir, ["web-app-a", "web-app-missing"]),
            )

    def test_a_malformed_definition_aborts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = Path(tmpdir)
            _write_role_users(roles_dir, "web-app-a", "alice: not-a-mapping\n")

            with self.assertRaises(SystemExit):
                required_usernames(roles_dir, ["web-app-a"])


class TestGenerateUserPasswords(unittest.TestCase):
    def _run(self, declared, application_ids, existing=None):
        yaml_rt = _yaml()
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = Path(tmpdir) / "roles"
            for application_id, body in declared.items():
                _write_role_users(roles_dir, application_id, body)

            host_vars_file = Path(tmpdir) / "host.yml"
            vault_pw_file = Path(tmpdir) / ".password"
            vault_pw_file.write_text("dummy\n", encoding="utf-8")

            if existing is not None:
                with host_vars_file.open("w", encoding="utf-8") as handle:
                    yaml_rt.dump(existing, handle)

            with (
                patch(f"{RUAMEL_MODULE}.VaultHandler") as vault,
                patch(f"{MODULE}.generate_user_password", return_value="plain"),
            ):
                vault.return_value.encrypt_string.side_effect = lambda _plain, name: (
                    VAULTED.format(name=name)
                )
                count = generate_user_passwords(
                    roles_dir=roles_dir,
                    application_ids=application_ids,
                    host_vars_file=host_vars_file,
                    vault_password_file=vault_pw_file,
                )

            if not host_vars_file.exists():
                return count, None
            with host_vars_file.open("r", encoding="utf-8") as handle:
                return count, yaml_rt.load(handle)

    def test_every_required_user_gets_a_vaulted_password(self):
        count, doc = self._run(
            {"web-app-a": "administrator: {}\nbiber: {}\n"}, ["web-app-a"]
        )

        self.assertEqual(2, count)
        for username in ("administrator", "biber"):
            node = doc["users"][username]["password"]
            self.assertEqual("!vault", getattr(node, "tag", None))

    def test_a_user_of_an_unresolved_role_is_not_pinned(self):
        count, doc = self._run(
            {"web-app-a": "alice: {}\n", "web-app-b": "bob: {}\n"}, ["web-app-a"]
        )

        self.assertEqual(1, count)
        self.assertIn("alice", doc["users"])
        self.assertNotIn("bob", doc["users"])

    def test_an_existing_password_is_never_overwritten(self):
        existing = CommentedMap()
        users = CommentedMap()
        biber = CommentedMap()
        biber["password"] = "KEEP_ME"
        users["biber"] = biber
        existing["users"] = users

        count, doc = self._run(
            {"web-app-a": "administrator: {}\nbiber: {}\n"},
            ["web-app-a"],
            existing=existing,
        )

        self.assertEqual(1, count)
        self.assertEqual("KEEP_ME", doc["users"]["biber"]["password"])
        self.assertEqual(
            "!vault", getattr(doc["users"]["administrator"]["password"], "tag", None)
        )

    def test_a_second_run_writes_nothing(self):
        yaml_rt = _yaml()
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = Path(tmpdir) / "roles"
            _write_role_users(roles_dir, "web-app-a", "biber: {}\n")

            host_vars_file = Path(tmpdir) / "host.yml"
            vault_pw_file = Path(tmpdir) / ".password"
            vault_pw_file.write_text("dummy\n", encoding="utf-8")

            with (
                patch(f"{RUAMEL_MODULE}.VaultHandler") as vault,
                patch(f"{MODULE}.generate_user_password", return_value="plain"),
            ):
                vault.return_value.encrypt_string.side_effect = lambda _plain, name: (
                    VAULTED.format(name=name)
                )
                first = generate_user_passwords(
                    roles_dir=roles_dir,
                    application_ids=["web-app-a"],
                    host_vars_file=host_vars_file,
                    vault_password_file=vault_pw_file,
                )
                with host_vars_file.open("r", encoding="utf-8") as handle:
                    after_first = yaml_rt.load(handle)
                second = generate_user_passwords(
                    roles_dir=roles_dir,
                    application_ids=["web-app-a"],
                    host_vars_file=host_vars_file,
                    vault_password_file=vault_pw_file,
                )
                with host_vars_file.open("r", encoding="utf-8") as handle:
                    after_second = yaml_rt.load(handle)

        self.assertEqual(1, first)
        self.assertEqual(0, second)
        self.assertEqual(
            str(after_first["users"]["biber"]["password"]),
            str(after_second["users"]["biber"]["password"]),
        )

    def test_other_inventory_keys_survive(self):
        existing = CommentedMap()
        existing["TLS_ENABLED"] = True

        _count, doc = self._run({"web-app-a": "biber: {}\n"}, ["web-app-a"], existing)

        self.assertIs(True, doc["TLS_ENABLED"])

    def test_no_required_users_writes_no_file(self):
        count, doc = self._run({"web-app-a": "alice: {}\n"}, [])

        self.assertEqual(0, count)
        self.assertIsNone(doc)


class TestGeneratedPasswordIsShellSafe(unittest.TestCase):
    """The value travels Ansible -> shell -> container exec -> runtime env."""

    def test_no_punctuation_survives_into_a_user_password(self):
        for _ in range(200):
            password = generate_user_password()
            self.assertTrue(
                password.isalnum(),
                f"{password!r} carries punctuation; roles used to declare their "
                "own alphanumeric credential precisely because the exec chain "
                "mangles it",
            )

    def test_the_password_is_long_enough_to_afford_the_smaller_alphabet(self):
        self.assertGreaterEqual(len(generate_user_password()), 64)


class TestRealisticInventoryRoundTrip(unittest.TestCase):
    """The generator rewrites the whole host_vars, so nothing else may shift."""

    def _pin(self, tmpdir: Path):
        roles_dir = tmpdir / "roles"
        _write_role_users(roles_dir, "web-app-a", "biber: {}\n")

        host_vars_file = tmpdir / "host.yml"
        host_vars_file.write_text(REALISTIC_HOST_VARS, encoding="utf-8")
        vault_pw_file = tmpdir / ".password"
        vault_pw_file.write_text("dummy\n", encoding="utf-8")

        with (
            patch(f"{RUAMEL_MODULE}.VaultHandler") as vault,
            patch(f"{MODULE}.generate_user_password", return_value="plain"),
        ):
            vault.return_value.encrypt_string.side_effect = lambda _plain, name: (
                VAULTED.format(name=name)
            )
            generate_user_passwords(
                roles_dir=roles_dir,
                application_ids=["web-app-a"],
                host_vars_file=host_vars_file,
                vault_password_file=vault_pw_file,
            )
        return host_vars_file

    def test_comments_and_vault_scalars_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_vars_file = self._pin(Path(tmp))
            written = read_text(host_vars_file)

        self.assertIn(
            "# Deployment-wide switches. This comment must survive the round trip.",
            written,
        )
        self.assertIn("# The role's own generated secret.", written)
        self.assertIn("# trailing comment", written)
        self.assertIn("ansible_become_password: !vault |", written)
        self.assertIn("api_key: !vault |", written)
        self.assertIn("3131316536383864370a", written)
        self.assertIn("6161326533353863", written)

    def test_every_pre_existing_value_is_unchanged(self):
        yaml_rt = _yaml()
        with tempfile.TemporaryDirectory() as tmp:
            host_vars_file = self._pin(Path(tmp))
            with host_vars_file.open("r", encoding="utf-8") as handle:
                doc = yaml_rt.load(handle)

        self.assertIs(True, doc["TLS_ENABLED"])
        self.assertIs(True, doc["applications"]["web-app-a"]["features"]["matomo"])
        self.assertEqual(
            "!vault",
            getattr(
                doc["applications"]["web-app-a"]["credentials"]["api_key"], "tag", None
            ),
        )
        self.assertEqual(
            "!vault", getattr(doc["users"]["biber"]["password"], "tag", None)
        )

    def test_the_generated_block_passes_the_inventory_validator(self):
        yaml_rt = _yaml()
        with tempfile.TemporaryDirectory() as tmp:
            host_vars_file = self._pin(Path(tmp))
            with host_vars_file.open("r", encoding="utf-8") as handle:
                doc = yaml_rt.load(handle)

        errors = compare_user_keys(
            doc["users"], {"biber": {"username": "biber"}}, "test"
        )

        self.assertEqual([], errors)


class TestHandoffToCredentialsGenerator(unittest.TestCase):
    """Credential generation rewrites the same document immediately afterwards."""

    def test_the_pinned_users_survive_credentials_generation(self):
        yaml_rt = _yaml()
        snippet = yaml_rt.load(
            "applications:\n  web-app-a:\n    credentials:\n      api_key: generated\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            roles_dir = tmpdir / "roles"
            _write_role_users(roles_dir, "web-app-a", "biber: {}\n")

            host_vars_file = tmpdir / "host.yml"
            vault_pw_file = tmpdir / ".password"
            vault_pw_file.write_text("dummy\n", encoding="utf-8")

            with (
                patch(f"{RUAMEL_MODULE}.VaultHandler") as vault,
                patch(f"{MODULE}.generate_user_password", return_value="plain"),
            ):
                vault.return_value.encrypt_string.side_effect = lambda _plain, name: (
                    VAULTED.format(name=name)
                )
                generate_user_passwords(
                    roles_dir=roles_dir,
                    application_ids=["web-app-a"],
                    host_vars_file=host_vars_file,
                    vault_password_file=vault_pw_file,
                )

            with patch(
                f"{CREDENTIALS_MODULE}._generate_credentials_snippet_for_app",
                return_value=snippet,
            ):
                generate_credentials_for_roles(
                    application_ids=["web-app-a"],
                    roles_dir=roles_dir,
                    host_vars_file=host_vars_file,
                    vault_password_file=vault_pw_file,
                    project_root=tmpdir,
                    env=None,
                )

            with host_vars_file.open("r", encoding="utf-8") as handle:
                doc = yaml_rt.load(handle)

        self.assertEqual(
            "!vault", getattr(doc["users"]["biber"]["password"], "tag", None)
        )
        self.assertEqual(
            "generated", doc["applications"]["web-app-a"]["credentials"]["api_key"]
        )


@unittest.skipIf(
    shutil.which("ansible-vault") is None, "ansible-vault is not installed"
)
class TestAgainstRealAnsibleVault(unittest.TestCase):
    """The mocked snippet shape is an assumption until ansible-vault confirms it."""

    def test_a_real_vault_value_is_written_and_reparsed(self):
        yaml_rt = _yaml()
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            roles_dir = tmpdir / "roles"
            _write_role_users(roles_dir, "web-app-a", "biber: {}\n")

            host_vars_file = tmpdir / "host.yml"
            vault_pw_file = tmpdir / ".password"
            vault_pw_file.write_text("s3cr3t-vault-password\n", encoding="utf-8")

            count = generate_user_passwords(
                roles_dir=roles_dir,
                application_ids=["web-app-a"],
                host_vars_file=host_vars_file,
                vault_password_file=vault_pw_file,
            )

            written = read_text(host_vars_file)
            with host_vars_file.open("r", encoding="utf-8") as handle:
                doc = yaml_rt.load(handle)

            second = generate_user_passwords(
                roles_dir=roles_dir,
                application_ids=["web-app-a"],
                host_vars_file=host_vars_file,
                vault_password_file=vault_pw_file,
            )

        self.assertEqual(1, count)
        self.assertEqual(0, second)
        self.assertIn("$ANSIBLE_VAULT;1.1;AES256", written)
        self.assertEqual(
            "!vault", getattr(doc["users"]["biber"]["password"], "tag", None)
        )


if __name__ == "__main__":
    unittest.main()
