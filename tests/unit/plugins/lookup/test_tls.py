import sys
import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

# Make "ansible.module_utils.tls_common" importable during plain unit tests.
import utils.tls_common as _tls_common
from plugins.lookup.tls import LookupModule

sys.modules.setdefault("ansible.module_utils.tls_common", _tls_common)


class TestTlsResolveLookup(unittest.TestCase):
    def setUp(self):
        self.lookup = LookupModule()

        self.domains = {
            "web-app-a": "a.example",
            "web-app-b": ["b.example", "b-alt.example"],
            "web-app-c": {"primary": "c.example", "api": "api.c.example"},
        }

        self.applications = {
            "web-app-a": {},
            "web-app-b": {"server": {"tls": {"flavor": "self_signed"}}},
            "web-app-c": {"server": {"tls": {"enabled": False}}},
        }

        self.base_vars = {
            "domains": self.domains,
            "applications": self.applications,
            "TLS_ENABLED": True,
            "TLS_MODE": "letsencrypt",
        }

        # Route get_merged_domains / get_merged_applications through
        # variables['domains'] / variables['applications'] so tests stay hermetic.
        def _domains_from_vars(*, variables=None, **_kwargs):
            return (variables or {}).get("domains", {})

        def _applications_from_vars(*, variables=None, **_kwargs):
            return (variables or {}).get("applications", {})

        self._patchers = [
            patch(
                "plugins.lookup.tls.get_merged_domains",
                side_effect=_domains_from_vars,
            ),
            patch(
                "plugins.lookup.tls.get_merged_applications",
                side_effect=_applications_from_vars,
            ),
        ]
        for p in self._patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patchers])

    def test_domain_term_auto_mode(self):
        out = self.lookup.run(["a.example"], variables=self.base_vars)[0]
        self.assertEqual(out["application_id"], "web-app-a")
        self.assertEqual(out["domain"], "a.example")
        self.assertTrue(out["enabled"])
        self.assertEqual(out["mode"], "letsencrypt")
        self.assertEqual(out["protocols"]["web"], "https")
        self.assertEqual(out["ports"]["web"], 443)
        self.assertEqual(out["url"]["base"], "https://a.example/")

    def test_app_term_forced_app(self):
        out = self.lookup.run(["web-app-a"], variables=self.base_vars, mode="app")[0]
        self.assertEqual(out["application_id"], "web-app-a")
        self.assertEqual(out["domain"], "a.example")

    def test_app_override_flavor(self):
        out = self.lookup.run(["web-app-b"], variables=self.base_vars, mode="app")[0]
        self.assertEqual(out["mode"], "self_signed")

    def test_app_override_enabled_false(self):
        out = self.lookup.run(["web-app-c"], variables=self.base_vars, mode="app")[0]
        self.assertFalse(out["enabled"])
        self.assertEqual(out["mode"], "off")
        self.assertEqual(out["protocols"]["web"], "http")
        self.assertEqual(out["ports"]["web"], 80)

    def test_domains_all_contains_primary_first(self):
        out = self.lookup.run(["web-app-b"], variables=self.base_vars, mode="app")[0]
        self.assertEqual(out["domains"]["primary"], "b.example")
        self.assertEqual(out["domains"]["all"], ["b.example", "b-alt.example"])

    def test_want_path_returns_scalar(self):
        val = self.lookup.run(
            ["web-app-a", "url.base"], variables=self.base_vars, mode="app"
        )[0]
        self.assertEqual(val, "https://a.example/")

    def test_missing_required_vars(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-a"], variables={})

    def test_invalid_tls_mode_default(self):
        bad = dict(self.base_vars)
        bad["TLS_MODE"] = "invalid"
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-a"], variables=bad, mode="app")

    def test_invalid_forced_mode(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-a"], variables=self.base_vars, mode="nope")

    def test_www_prefix_falls_back_to_bare_domain(self):
        out = self.lookup.run(["www.a.example"], variables=self.base_vars)[0]
        self.assertEqual(out["application_id"], "web-app-a")
        self.assertEqual(out["domain"], "a.example")

    def test_www_prefix_with_unknown_bare_still_raises(self):
        with self.assertRaises(AnsibleError) as ctx:
            self.lookup.run(["www.unknown.example"], variables=self.base_vars)
        self.assertIn("not found", str(ctx.exception))

    def test_non_www_unregistered_still_raises(self):
        with self.assertRaises(AnsibleError) as ctx:
            self.lookup.run(["unknown.example"], variables=self.base_vars)
        self.assertIn("not found", str(ctx.exception))

    def test_term_with_unresolved_jinja_is_templated(self):
        class _FakeTemplar:
            def __init__(self, mapping):
                self._mapping = mapping
                self.calls = []

            def template(self, value):
                self.calls.append(value)
                return self._mapping.get(value, value)

        fake = _FakeTemplar({"{{ MY_DOMAIN }}": "a.example"})
        self.lookup._templar = fake

        out = self.lookup.run(["{{ MY_DOMAIN }}"], variables=self.base_vars)[0]

        self.assertEqual(out["application_id"], "web-app-a")
        self.assertEqual(out["domain"], "a.example")
        self.assertIn("{{ MY_DOMAIN }}", fake.calls)


if __name__ == "__main__":
    unittest.main()
