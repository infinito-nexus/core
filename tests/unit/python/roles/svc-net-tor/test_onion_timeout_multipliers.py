import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

SERVICES_PATH = PROJECT_ROOT / "roles" / "svc-net-tor" / ROLE_FILE_META_SERVICES
FLAVOR_DIR = PROJECT_ROOT / "roles" / "svc-net-tor" / "tasks" / "flavor"


class TestOnionTimeoutMultipliers(unittest.TestCase):
    def test_every_tor_flavor_has_a_multiplier(self) -> None:
        multipliers = load_yaml_any(str(SERVICES_PATH))["tor"]["timeout_multipliers"]
        flavors = {path.name for path in FLAVOR_DIR.iterdir() if path.is_dir()}

        self.assertTrue(flavors)
        self.assertEqual(
            sorted(flavors - set(multipliers)),
            [],
            "the Playwright run and the CSP health check look the multiplier up "
            "by the tor flavor and fail without one",
        )
        for flavor, value in multipliers.items():
            self.assertIsInstance(value, int, flavor)
            self.assertGreaterEqual(value, 1, flavor)


if __name__ == "__main__":
    unittest.main()
