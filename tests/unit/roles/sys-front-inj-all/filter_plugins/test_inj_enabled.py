import importlib.util
import sys
import unittest
from importlib import import_module

from . import PROJECT_ROOT

PLUGIN_PATH = (
    PROJECT_ROOT / "roles" / "sys-front-inj-all" / "filter_plugins" / "inj_enabled.py"
)

# Ensure 'utils' is importable under its canonical package name
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import the same module path the plugin uses
mu_mod = import_module("utils.roles.applications.config")
AppConfigKeyError = mu_mod.AppConfigKeyError

# Load inj_enabled filter plugin from file
spec = importlib.util.spec_from_file_location("inj_enabled", str(PLUGIN_PATH))
inj_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inj_mod)
FilterModule = inj_mod.FilterModule


def _get_filter():
    fm = FilterModule()
    flt = fm.filters().get("inj_enabled")
    assert callable(flt), "inj_enabled filter not found or not callable"
    return flt


class TestInjEnabledFilter(unittest.TestCase):
    def setUp(self):
        self.filter = _get_filter()

    def test_basic_build(self):
        applications = {
            "myapp": {
                "services": {
                    "javascript": {"enabled": True},
                    "logout": {"enabled": False},
                    "css": {"enabled": True},
                    "matomo": {"enabled": False},
                    "dashboard": {"enabled": True},
                }
            }
        }
        features = ["javascript", "logout", "css", "matomo", "dashboard"]
        result = self.filter(applications, "myapp", features)
        self.assertEqual(
            result,
            {
                "javascript": True,
                "logout": False,
                "css": True,
                "matomo": False,
                "dashboard": True,
            },
        )

    def test_missing_keys_return_default_false(self):
        applications = {
            "app": {
                "services": {
                    "javascript": {"enabled": True},
                    # logout/css missing
                }
            }
        }
        result = self.filter(
            applications, "app", ["javascript", "logout", "css"], default=False
        )
        self.assertEqual(result["javascript"], True)
        self.assertEqual(result["logout"], False)
        self.assertEqual(result["css"], False)

    def test_default_true_applied_to_missing(self):
        applications = {"app": {"services": {}}}
        result = self.filter(applications, "app", ["logout", "css"], default=True)
        self.assertEqual(result, {"logout": True, "css": True})

    def test_custom_prefix(self):
        # inj_enabled always appends ".<feature>.enabled" to the prefix
        applications = {
            "app": {"flags": {"logout": {"enabled": True}, "css": {"enabled": False}}}
        }
        result = self.filter(
            applications, "app", ["logout", "css"], prefix="flags", default=False
        )
        self.assertEqual(result, {"logout": True, "css": False})

    def test_missing_application_id_raises(self):
        applications = {"other": {"services": {"logout": {"enabled": True}}}}
        with self.assertRaises(AppConfigKeyError):
            _ = self.filter(applications, "unknown-app", ["logout"])

    def test_truthy_string_is_returned_as_is(self):
        applications = {"app": {"services": {"logout": {"enabled": "true"}}}}
        result = self.filter(applications, "app", ["logout"], default=False)
        self.assertEqual(result["logout"], "true")

    def test_nonexistent_feature_path_uses_default(self):
        applications = {"app": {"services": {}}}
        result = self.filter(applications, "app", ["nonexistent"], default=False)
        self.assertEqual(result["nonexistent"], False)


if __name__ == "__main__":
    unittest.main()
