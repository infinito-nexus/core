import unittest

from utils.cache import PROJECT_ROOT
from utils.cache import applications as cache_apps

ROLE_DIR = PROJECT_ROOT / "roles/web-app-nextcloud"
FORMER_PLUGIN_DIR = ROLE_DIR / "vars/plugins"
FORMER_PLUGIN_IDS = (
    "bbb",
    "onlyoffice",
    "richdocuments",
    "sociallogin",
    "spreed",
    "user_ldap",
    "whiteboard",
    "xwiki",
)


class TestPluginConfigAbsorbedIntoAddons(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        defaults = cache_apps.get_application_defaults(roles_dir=PROJECT_ROOT / "roles")
        cls.addons = defaults["web-app-nextcloud"]["addons"]

    def test_no_per_plugin_config_file_remains(self):
        self.assertEqual(
            [], sorted(path.name for path in FORMER_PLUGIN_DIR.glob("*.yml"))
        )

    def test_every_former_plugin_payload_lives_under_its_addon_config(self):
        for addon_id in FORMER_PLUGIN_IDS:
            with self.subTest(addon=addon_id):
                config = self.addons[addon_id]["config"]
                self.assertIsInstance(config, dict)
                self.assertTrue(config)


if __name__ == "__main__":
    unittest.main()
