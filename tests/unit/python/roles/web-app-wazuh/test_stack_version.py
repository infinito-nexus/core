import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

SERVICES = PROJECT_ROOT / "roles" / "web-app-wazuh" / ROLE_FILE_META_SERVICES
STACK = ("manager", "indexer", "console")


class TestStackVersion(unittest.TestCase):
    def test_manager_indexer_and_dashboard_share_one_version(self):
        services = load_yaml_any(str(SERVICES))
        versions = {name: services[name]["version"] for name in STACK}
        self.assertEqual(len(set(versions.values())), 1, versions)


if __name__ == "__main__":
    unittest.main()
