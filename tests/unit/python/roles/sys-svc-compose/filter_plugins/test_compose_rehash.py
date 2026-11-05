import importlib.util
import re
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from plugins.lookup.compose_volumes import compose_volumes
from utils import PROJECT_ROOT
from utils.cache import _reset_cache_for_tests
from utils.cache.yaml import dump_yaml_str, load_yaml_str

_spec = importlib.util.spec_from_file_location(
    "compose_rehash",
    PROJECT_ROOT / "roles/sys-svc-compose/filter_plugins/compose_rehash.py",
)
compose_rehash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compose_rehash)

APPLICATIONS = {
    "app": {
        "services": {
            "mariadb": {"enabled": False, "shared": False},
            "redis": {"enabled": False},
            "sso": {"enabled": False, "flavor": "oauth2"},
        }
    }
}


def render_in_a_fresh_worker(configs, secrets):
    _reset_cache_for_tests()
    return load_yaml_str(
        compose_volumes(
            APPLICATIONS,
            "app",
            extra_configs={key: {"file": str(path)} for key, path in configs.items()},
            extra_secrets={key: {"file": str(path)} for key, path in secrets.items()},
            dir_var_lib="/var/lib/infinito",
        )
    )


def flush_in_a_fresh_worker(compose):
    _reset_cache_for_tests()
    text = dump_yaml_str(compose)
    for entry in compose_rehash.compose_hashed_entries(compose):
        text = re.sub(
            rf"(?<![\w.-]){re.escape(entry['name'])}(?![\w.-])",
            compose_rehash.compose_rehashed_name(entry),
            text,
        )
    return load_yaml_str(text)


class TestHashedEntries(unittest.TestCase):
    def test_only_names_ending_in_their_key_and_a_hash(self):
        compose = {
            "services": {"app": {"configs": [{"source": "roles_yml"}]}},
            "configs": {
                "roles_yml": {
                    "file": "/c/roles.yml",
                    "name": "wazuh_roles_yml_e614d1ac",
                },
                "pinned": {"file": "/c/p.yml", "name": "fixed_name_deadbeef"},
                "external": {"external": True, "name": "shared_x_12345678"},
            },
            "secrets": {"authd": {"file": "/c/authd", "name": "wazuh_authd_810ae9fb"}},
        }
        self.assertEqual(
            compose_rehash.compose_hashed_entries(compose),
            [
                {
                    "name": "wazuh_roles_yml_e614d1ac",
                    "entity": "wazuh",
                    "key": "roles_yml",
                    "file": "/c/roles.yml",
                },
                {
                    "name": "wazuh_authd_810ae9fb",
                    "entity": "wazuh",
                    "key": "authd",
                    "file": "/c/authd",
                },
            ],
        )

    def test_no_configs_or_secrets(self):
        self.assertEqual(compose_rehash.compose_hashed_entries({"services": {}}), [])


class TestDeploySequence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(_reset_cache_for_tests)
        self.config = Path(self._tmp.name) / "roles.yml"
        self.secret = Path(self._tmp.name) / "authd.pass"
        self.config.write_text("roles:\n  - admin\n", encoding="utf-8")
        self.secret.write_text("old-pass\n", encoding="utf-8")

    def render(self):
        return render_in_a_fresh_worker(
            {"roles_yml": self.config}, {"authd": self.secret}
        )

    def test_file_written_after_the_render_is_not_one_deploy_behind(self):
        deploy_one = self.render()
        self.config.write_text("roles:\n  - admin\n  - reader\n", encoding="utf-8")
        self.secret.write_text("new-pass\n", encoding="utf-8")

        flushed = flush_in_a_fresh_worker(deploy_one)
        deploy_two = self.render()

        self.assertNotEqual(deploy_one, deploy_two)
        self.assertEqual(flushed, deploy_two)

    def test_unchanged_files_keep_every_name(self):
        deploy_one = self.render()
        self.assertEqual(flush_in_a_fresh_worker(deploy_one), deploy_one)

    def test_file_the_controller_cannot_read_keeps_the_name_the_render_gives_it(self):
        with mock.patch(
            "utils.cache.files.read_text", side_effect=FileNotFoundError("remote")
        ):
            deploy_one = self.render()
            flushed = flush_in_a_fresh_worker(deploy_one)
            deploy_two = self.render()

        self.assertEqual(flushed, deploy_two)


if __name__ == "__main__":
    unittest.main()
