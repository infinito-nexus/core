import unittest
from pathlib import PurePosixPath

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

WAZUH_VARS = PROJECT_ROOT / "roles" / "web-app-wazuh" / ROLE_FILE_VARS_MAIN


def opted_in_entities():
    roles = PROJECT_ROOT / "roles"
    for services in sorted(roles.glob(f"*/{ROLE_FILE_META_SERVICES}")):
        role = services.relative_to(roles).parts[0]
        wazuh = (load_yaml_any(str(services)) or {}).get("wazuh") or {}
        if wazuh.get("rule_block"):
            yield role, get_entity_name(role)


class TestRulesetFileOrder(unittest.TestCase):
    def test_base_files_sort_before_every_app_file(self):
        base = {
            PurePosixPath(entry["dest"]).parent.name: PurePosixPath(entry["dest"]).name
            for entry in load_yaml_any(str(WAZUH_VARS))["WAZUH_RULESET_BASE_FILES"]
        }
        self.assertEqual(set(base), {"decoders", "rules"})
        entities = list(opted_in_entities())
        self.assertTrue(entities)
        for role, entity in entities:
            for kind, base_name in base.items():
                with self.subTest(role=role, kind=kind):
                    self.assertLess(base_name, f"{entity}_{kind}.xml")

    def test_base_files_sort_between_wazuh_defaults_and_app_files(self):
        for entry in load_yaml_any(str(WAZUH_VARS))["WAZUH_RULESET_BASE_FILES"]:
            name = PurePosixPath(entry["dest"]).name
            with self.subTest(dest=entry["dest"]):
                self.assertGreater(name, "0999-~")
                self.assertLess(name, "a")


if __name__ == "__main__":
    unittest.main()
