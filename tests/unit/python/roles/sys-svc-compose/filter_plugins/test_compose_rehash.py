import base64
import importlib.util
import tempfile
import unittest
from pathlib import Path

from plugins.lookup.compose_volumes import _config_secret_name
from utils import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "compose_rehash",
    PROJECT_ROOT / "roles/sys-svc-compose/filter_plugins/compose_rehash.py",
)
compose_rehash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compose_rehash)


def slurped(data):
    return base64.b64encode(data).decode()


class TestHashedEntries(unittest.TestCase):
    def test_only_names_ending_in_their_key_and_a_hash(self):
        compose = {
            "services": {"app": {"configs": [{"source": "roles_yml"}]}},
            "configs": {
                "roles_yml": {"file": "/c/roles.yml", "name": "wazuh_roles_yml_e614d1ac"},
                "pinned": {"file": "/c/p.yml", "name": "fixed_name_deadbeef"},
                "external": {"external": True, "name": "shared_x_12345678"},
            },
            "secrets": {"authd": {"file": "/c/authd", "name": "wazuh_authd_810ae9fb"}},
        }
        self.assertEqual(
            compose_rehash.compose_hashed_entries(compose),
            [
                {"name": "wazuh_roles_yml_e614d1ac", "file": "/c/roles.yml"},
                {"name": "wazuh_authd_810ae9fb", "file": "/c/authd"},
            ],
        )

    def test_no_configs_or_secrets(self):
        self.assertEqual(compose_rehash.compose_hashed_entries({"services": {}}), [])
        self.assertEqual(compose_rehash.compose_hashed_entries(None), [])


class TestRehashedName(unittest.TestCase):
    def assert_matches_lookup(self, data):
        with tempfile.NamedTemporaryFile("wb", delete=False) as handle:
            handle.write(data)
        try:
            expected = _config_secret_name("wazuh", "roles_yml", handle.name)
        finally:
            Path(handle.name).unlink()
        self.assertEqual(
            compose_rehash.compose_rehashed_name("wazuh_roles_yml_00000000", slurped(data)),
            expected,
        )

    def test_equals_the_compose_volumes_name(self):
        self.assert_matches_lookup(b"roles:\n  - admin\n")

    def test_crlf_and_unicode_hash_like_the_lookup(self):
        self.assert_matches_lookup("a: 1\r\nb: ä\r\n".encode())

    def test_unchanged_content_keeps_the_name(self):
        name = compose_rehash.compose_rehashed_name("x_k_00000000", slurped(b"v\n"))
        self.assertEqual(compose_rehash.compose_rehashed_name(name, slurped(b"v\n")), name)


if __name__ == "__main__":
    unittest.main()
