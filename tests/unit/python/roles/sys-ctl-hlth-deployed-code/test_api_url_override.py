import unittest

from plugins.lookup.config import LookupModule
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_VARS_MAIN

ROLE = "sys-ctl-hlth-deployed-code"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
PATH = "services.deployed-code.providers.github.api_url"
OVERRIDE = "https://ghe.example.org/api/v3"  # nocheck: url


class TestDeployedCodeApiUrl(unittest.TestCase):
    def resolve(self, variables):
        return LookupModule().run(
            [ROLE, PATH], variables=variables, roles_dir=str(PROJECT_ROOT / "roles")
        )[0]

    def test_role_default_is_the_public_github_api(self):
        self.assertEqual(self.resolve({}), "https://api.github.com")

    def test_inventory_override_wins(self):
        variables = {
            "applications": {
                ROLE: {
                    "services": {
                        "deployed-code": {
                            "providers": {"github": {"api_url": OVERRIDE}}
                        }
                    }
                }
            }
        }
        self.assertEqual(self.resolve(variables), OVERRIDE)

    def test_the_check_reads_the_url_only_through_the_config_lookup(self):
        role_vars = load_yaml(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        self.assertIn(
            f"lookup('config', '{ROLE}', '{PATH}')",
            role_vars["HLTH_DEPLOYED_CODE_API_URL"],
        )
        defaults = load_yaml(str(ROLE_DIR / ROLE_FILE_DEFAULTS_MAIN))
        self.assertNotIn("HLTH_DEPLOYED_CODE_API_URL", defaults)


if __name__ == "__main__":
    unittest.main()
