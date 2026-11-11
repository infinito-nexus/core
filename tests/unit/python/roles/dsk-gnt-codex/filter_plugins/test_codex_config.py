import importlib.util
import tomllib
import unittest

import jinja2
from ansible.errors import AnsibleFilterError

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "dsk-gnt-codex"
KEY_ENV = load_yaml(ROLE / ROLE_FILE_VARS_MAIN)["agnt_codex_key_env"]

FOREIGN = """# personal codex settings
approval_policy = "never"
model_reasoning_effort = "high"

[projects."/home/alice/src"]
trust_level = "trusted"

[mcp_servers.blender]
command = "/home/alice/.local/bin/mcp-for-blender"

[mcp_servers.docs.env]
LOG_LEVEL = "debug"
"""

LEGACY = f"""model = "old-model"
model_provider = "infinito"

[model_providers.infinito]
name = "Infinito.Nexus gateway"
base_url = "http://127.0.0.1:3999/v1"
env_key = "{KEY_ENV}"
wire_api = "chat"

[mcp_servers.blender]
command = "/home/alice/.local/bin/mcp-for-blender"
"""


def _load_merge():
    path = ROLE / "filter_plugins" / "codex_config.py"
    spec = importlib.util.spec_from_file_location("codex_config_filter", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.codex_config_merge


def _managed(model="gateway-model"):
    template = read_text(str(ROLE / "templates" / "config.toml.j2"))
    return jinja2.Template(template, keep_trailing_newline=True).render(
        agnt_codex_model=model,
        SOFTWARE_NAME="Infinito.Nexus",
        agnt_codex_gateway_url="http://127.0.0.1:4000/v1",
        agnt_codex_key_env=KEY_ENV,
    )


class TestCodexConfigMerge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.merge = staticmethod(_load_merge())

    def test_fresh_host_gets_exactly_the_managed_profile(self):
        self.assertEqual(self.merge("", _managed()), _managed())

    def test_foreign_keys_and_mcp_tables_survive_a_rerender(self):
        merged = tomllib.loads(self.merge(FOREIGN, _managed()))
        foreign = tomllib.loads(FOREIGN)
        for key in ("approval_policy", "model_reasoning_effort", "projects"):
            self.assertEqual(merged[key], foreign[key])
        self.assertEqual(merged["mcp_servers"], foreign["mcp_servers"])

    def test_foreign_comment_survives(self):
        self.assertIn("# personal codex settings", self.merge(FOREIGN, _managed()))

    def test_owned_keys_are_set(self):
        merged = tomllib.loads(self.merge(FOREIGN, _managed()))
        self.assertEqual(merged["model"], "gateway-model")
        self.assertEqual(merged["model_provider"], "infinito")
        self.assertEqual(
            merged["model_providers"]["infinito"]["base_url"],
            "http://127.0.0.1:4000/v1",
        )

    def test_profile_uses_the_wire_api_the_pinned_codex_accepts(self):
        profile = tomllib.loads(_managed())["model_providers"]["infinito"]
        self.assertEqual(profile["wire_api"], "responses")

    def test_legacy_profile_is_updated_in_place_without_duplicates(self):
        merged = self.merge(LEGACY, _managed())
        self.assertEqual(merged.count("[model_providers.infinito]"), 1)
        self.assertEqual(merged.count("\nmodel ="), 0)
        self.assertTrue(merged.startswith('model = "gateway-model"\n'))
        self.assertIn("[mcp_servers.blender]", merged)

    def test_foreign_key_inside_the_owned_table_survives(self):
        current = LEGACY.replace(
            'wire_api = "chat"\n', 'wire_api = "chat"\nrequest_max_retries = 7\n'
        )
        merged = tomllib.loads(self.merge(current, _managed()))
        self.assertEqual(
            merged["model_providers"]["infinito"]["request_max_retries"], 7
        )

    def test_second_merge_changes_nothing(self):
        once = self.merge(FOREIGN, _managed())
        self.assertEqual(self.merge(once, _managed()), once)

    def test_invalid_existing_config_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            self.merge("model = \n", _managed())

    def test_inline_owned_table_is_refused_instead_of_duplicated(self):
        current = 'model_providers = { infinito = { name = "x" } }\n'
        with self.assertRaises(AnsibleFilterError):
            self.merge(current, _managed())


if __name__ == "__main__":
    unittest.main()
