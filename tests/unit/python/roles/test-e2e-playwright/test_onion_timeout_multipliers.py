import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

VARS_PATH = PROJECT_ROOT / "roles" / "test-e2e-playwright" / ROLE_FILE_VARS_MAIN
FLAVOR_DIR = PROJECT_ROOT / "roles" / "svc-net-tor" / "tasks" / "flavor"


class TestOnionTimeoutMultipliers(unittest.TestCase):
    def test_every_tor_flavor_has_a_multiplier(self):
        multipliers = load_yaml_any(str(VARS_PATH))[
            "TEST_E2E_PLAYWRIGHT_ONION_TIMEOUT_MULTIPLIERS"
        ]
        flavors = {path.name for path in FLAVOR_DIR.iterdir() if path.is_dir()}

        self.assertTrue(flavors)
        self.assertEqual(
            sorted(flavors - set(multipliers)),
            [],
            "the Playwright run looks the multiplier up by the tor flavor and fails without one",
        )
        for flavor, value in multipliers.items():
            self.assertIsInstance(value, int, flavor)
            self.assertGreaterEqual(value, 1, flavor)


if __name__ == "__main__":
    unittest.main()
