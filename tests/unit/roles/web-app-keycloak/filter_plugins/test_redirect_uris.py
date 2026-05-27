import importlib.util
import sys
import types
import unittest

from utils.cache import PROJECT_ROOT

PLUGIN_PATH = (
    PROJECT_ROOT / "roles" / "web-app-keycloak" / "filter_plugins" / "redirect_uris.py"
)


def _load_module_from_path(name, file_path):
    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader, f"Cannot load spec for {file_path}"
    spec.loader.exec_module(module)
    return module


_STUBBED_MODULE_NAMES = (
    "utils",
    "utils.roles.applications",
    "utils.roles.applications.config",
    "utils.get_url",
)


class RedirectUrisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_sys_modules = {
            name: sys.modules[name]
            for name in _STUBBED_MODULE_NAMES
            if name in sys.modules
        }

        mu = types.ModuleType("utils")
        mu_apps = types.ModuleType("utils.roles.applications")
        mu_config = types.ModuleType("utils.roles.applications.config")
        mu_geturl = types.ModuleType("utils.get_url")

        # Define stub exceptions
        class AppConfigKeyError(Exception):
            pass

        class ConfigEntryNotSetError(Exception):
            pass

        # Define a practical get that understands dotted keys
        def get(applications, app_id, dotted, default=None):
            data = applications.get(app_id, {})
            cur = data
            for part in dotted.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    return default
            return cur

        # Define a simple get_url matching your utils/get_url contract
        # get_url(domains, application_id, protocol) -> "<protocol>://<domain>"
        def get_url(domains, application_id, protocol):
            domain = domains[application_id]
            return f"{protocol}://{domain}"

        # Attach to stub modules
        mu_config.get = staticmethod(get)
        mu_config.AppConfigKeyError = AppConfigKeyError
        mu_config.ConfigEntryNotSetError = ConfigEntryNotSetError

        mu_geturl.get_url = staticmethod(get_url)

        # Register in sys.modules so plugin imports succeed
        sys.modules["utils"] = mu
        sys.modules["utils.roles.applications"] = mu_apps
        sys.modules["utils.roles.applications.config"] = mu_config
        sys.modules["utils.get_url"] = mu_geturl

        # Load the plugin by path
        cls.plugin = _load_module_from_path(
            "test_target.redirect_uris", str(PLUGIN_PATH)
        )

        # Keep originals for per-test monkeypatching
        cls._orig_get = cls.plugin.get
        cls._orig_get_url = cls.plugin.get_url

    def tearDown(self):
        # Restore plugin functions if a test monkeypatched them
        self.plugin.get = self._orig_get
        self.plugin.get_url = self._orig_get_url

    @classmethod
    def tearDownClass(cls):
        for name in _STUBBED_MODULE_NAMES:
            if name in cls._orig_sys_modules:
                sys.modules[name] = cls._orig_sys_modules[name]
            else:
                sys.modules.pop(name, None)

    def test_single_domain_oauth2_enabled(self):
        domains = {"app1": "example.org"}
        applications = {"app1": {"services": {"oauth2": {"enabled": True}}}}
        result = self.plugin.redirect_uris(domains, applications, web_protocol="https")
        self.assertEqual(result, ["https://example.org/*"])

    def test_multiple_domains_oidc_enabled(self):
        domains = {"appX": ["a.example.org", "b.example.org"]}
        applications = {"appX": {"services": {"oidc": {"enabled": True}}}}
        result = self.plugin.redirect_uris(domains, applications, web_protocol="https")
        self.assertCountEqual(
            result, ["https://a.example.org/*", "https://b.example.org/*"]
        )

    def test_feature_missing_is_skipped(self):
        domains = {"app1": "example.org"}
        applications = {"app1": {"features": {"oauth2": False, "oidc": False}}}
        result = self.plugin.redirect_uris(domains, applications)
        self.assertEqual(result, [])

    def test_protocol_and_wildcard_customization(self):
        domains = {"app1": "x.test"}
        applications = {"app1": {"services": {"oauth2": {"enabled": True}}}}
        result = self.plugin.redirect_uris(
            domains, applications, web_protocol="http", wildcard="/cb"
        )
        self.assertEqual(result, ["http://x.test/cb"])

    def test_dedup_default_true(self):
        domains = {"app1": ["dup.test", "dup.test", "other.test"]}
        applications = {"app1": {"services": {"oidc": {"enabled": True}}}}
        result = self.plugin.redirect_uris(domains, applications)
        self.assertEqual(result, ["https://dup.test/*", "https://other.test/*"])

    def test_dedup_false_keeps_duplicates(self):
        domains = {"app1": ["dup.test", "dup.test"]}
        applications = {"app1": {"services": {"oidc": {"enabled": True}}}}
        result = self.plugin.redirect_uris(domains, applications, dedup=False)
        self.assertEqual(result, ["https://dup.test/*", "https://dup.test/*"])

    def test_invalid_domains_type_raises(self):
        with self.assertRaises(self.plugin.AnsibleFilterError):
            self.plugin.redirect_uris(["not-a-dict"], {})  # type: ignore[arg-type]

    def test_get_url_failure_is_wrapped(self):
        # Make get_url raise an arbitrary error; plugin should re-raise AnsibleFilterError
        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        self.plugin.get_url = boom

        domains = {"app1": "example.org"}
        applications = {"app1": {"services": {"oauth2": {"enabled": True}}}}

        with self.assertRaises(self.plugin.AnsibleFilterError) as ctx:
            self.plugin.redirect_uris(domains, applications)
        self.assertIn("get_url failed", str(ctx.exception))

    def test_get_exception_is_handled_as_no_feature(self):
        # Make get raise AppConfigKeyError; plugin should treat as not enabled and skip
        def raising_get(*args, **kwargs):
            raise self.plugin.AppConfigKeyError("missing key")

        self.plugin.get = raising_get

        domains = {"app1": "example.org"}
        applications = {
            "app1": {"services": {"oauth2": {"enabled": True}}}
        }  # value won't be read due to exception

        result = self.plugin.redirect_uris(domains, applications)
        self.assertEqual(result, [])

    def test_domain_value_dict_is_flattened_in_order(self):
        # Dict with mixed value types and a duplicate to verify stable dedup
        domains = {
            "app1": {
                "primary": "a.example.org",
                "alt": ["b.example.org", "b.example.org"],
                "nested": {"x": "c.example.org", "y": ["d.example.org"]},
            }
        }
        applications = {"app1": {"services": {"oauth2": {"enabled": True}}}}

        result = self.plugin.redirect_uris(domains, applications)

        self.assertEqual(
            result,
            [
                "https://a.example.org/*",
                "https://b.example.org/*",  # duplicate trimmed
                "https://c.example.org/*",
                "https://d.example.org/*",
            ],
        )


if __name__ == "__main__":
    unittest.main()
