import importlib
import sys
import unittest

from ansible.errors import AnsibleError

from utils.tls_common import (
    AVAILABLE_FLAVORS,
    align_domain_to_consumer,
    as_str,
    collect_domains_for_app,
    collect_domains_global,
    get_path,
    is_onion_domain,
    norm_domain,
    override_san_list,
    require,
    resolve_app_id_from_domain,
    resolve_enabled,
    resolve_le_name,
    resolve_mode,
    resolve_primary_domain_from_app,
    resolve_term,
    uniq_preserve,
    want_get,
)

# Make "ansible.module_utils.tls_common" importable during plain unit tests.
_tls_common = importlib.import_module("utils.tls_common")

sys.modules.setdefault("ansible.module_utils.tls_common", _tls_common)


class TestTlsCommon(unittest.TestCase):
    def setUp(self):
        self.domains = {
            "web-app-a": "a.example",
            "web-app-b": ["b.example", "b-alt.example"],
            "web-app-c": {"primary": "c.example", "api": "api.c.example"},
        }

    def test_as_str_and_norm_domain(self):
        self.assertEqual(as_str("  x  "), "x")
        self.assertEqual(norm_domain("  A.Example "), "a.example")

    def test_require_success_and_fail(self):
        v = {"X": 1}
        self.assertEqual(require(v, "X", int), 1)
        with self.assertRaises(AnsibleError):
            require(v, "MISSING", int)
        with self.assertRaises(AnsibleError):
            require(v, "X", str)

    def test_get_path(self):
        data = {"a": {"b": {"c": 1}}}
        self.assertEqual(get_path(data, "a.b.c"), 1)
        self.assertIsNone(get_path(data, "a.b.x"))
        self.assertEqual(get_path(data, "a.b.x", 42), 42)

    def test_want_get(self):
        data = {"a": {"b": 1}}
        self.assertEqual(want_get(data, "a.b"), 1)
        with self.assertRaises(AnsibleError):
            want_get(data, "a.x")

    def test_uniq_preserve_normalizes_and_dedupes(self):
        items = ["A.EXAMPLE", "a.example", "b.example", "B.EXAMPLE", "  "]
        self.assertEqual(uniq_preserve(items), ["a.example", "b.example"])

    def test_resolve_primary_domain_from_app(self):
        self.assertEqual(
            resolve_primary_domain_from_app(self.domains, "web-app-a", err_prefix="t"),
            "a.example",
        )
        self.assertEqual(
            resolve_primary_domain_from_app(self.domains, "web-app-b", err_prefix="t"),
            "b.example",
        )
        self.assertEqual(
            resolve_primary_domain_from_app(self.domains, "web-app-c", err_prefix="t"),
            "c.example",
        )
        with self.assertRaises(AnsibleError):
            resolve_primary_domain_from_app(self.domains, "missing", err_prefix="t")

    def test_resolve_app_id_from_domain(self):
        self.assertEqual(
            resolve_app_id_from_domain(self.domains, "a.example", err_prefix="t"),
            "web-app-a",
        )
        self.assertEqual(
            resolve_app_id_from_domain(self.domains, "API.C.EXAMPLE", err_prefix="t"),
            "web-app-c",
        )
        with self.assertRaises(AnsibleError):
            resolve_app_id_from_domain(self.domains, "nope.example", err_prefix="t")

    def test_collect_domains_for_app(self):
        self.assertEqual(
            collect_domains_for_app(self.domains, "web-app-a", err_prefix="t"),
            ["a.example"],
        )
        self.assertEqual(
            collect_domains_for_app(self.domains, "web-app-b", err_prefix="t"),
            ["b.example", "b-alt.example"],
        )
        self.assertEqual(
            collect_domains_for_app(self.domains, "web-app-c", err_prefix="t"),
            ["c.example", "api.c.example"],
        )

    def test_collect_domains_global(self):
        got = collect_domains_global(self.domains)
        self.assertEqual(
            got,
            ["a.example", "b.example", "b-alt.example", "c.example", "api.c.example"],
        )

    def test_resolve_term_domain_and_app(self):
        app_id, primary = resolve_term(
            "API.C.EXAMPLE", domains=self.domains, forced_mode="auto", err_prefix="t"
        )
        self.assertEqual(app_id, "web-app-c")
        self.assertEqual(primary, "api.c.example")

        app_id, primary = resolve_term(
            "web-app-b", domains=self.domains, forced_mode="app", err_prefix="t"
        )
        self.assertEqual(app_id, "web-app-b")
        self.assertEqual(primary, "b.example")

        with self.assertRaises(AnsibleError):
            resolve_term(
                "x", domains=self.domains, forced_mode="invalid", err_prefix="t"
            )

    def test_resolve_enabled_and_mode(self):
        app = {}
        self.assertTrue(resolve_enabled(app, True))
        self.assertFalse(resolve_enabled({"server": {"tls": {"enabled": False}}}, True))

        self.assertEqual(
            resolve_mode(app, True, "letsencrypt", err_prefix="t"), "letsencrypt"
        )
        self.assertEqual(resolve_mode(app, False, "letsencrypt", err_prefix="t"), "off")

        app2 = {"server": {"tls": {"flavor": "self_signed"}}}
        self.assertEqual(
            resolve_mode(app2, True, "letsencrypt", err_prefix="t"), "self_signed"
        )

        with self.assertRaises(AnsibleError):
            resolve_mode(
                {"server": {"tls": {"flavor": "nope"}}},
                True,
                "letsencrypt",
                err_prefix="t",
            )

    def test_is_onion_domain(self):
        self.assertTrue(is_onion_domain("abc.onion"))
        self.assertTrue(is_onion_domain("next.cloud.ABC123.ONION"))
        self.assertFalse(is_onion_domain("example.com"))
        self.assertFalse(is_onion_domain("onion.example.com"))
        self.assertFalse(is_onion_domain(""))

    def test_resolve_enabled_onion_always_off(self):
        # .onion forces TLS off regardless of default or per-app override.
        self.assertFalse(resolve_enabled({}, True, primary_domain="x.onion"))
        self.assertFalse(
            resolve_enabled(
                {"server": {"tls": {"enabled": True}}},
                True,
                primary_domain="app.abc.onion",
            )
        )
        # non-onion keeps normal behavior
        self.assertTrue(resolve_enabled({}, True, primary_domain="example.com"))

    def test_align_domain_to_consumer_clearnet_consumer_gets_clearnet(self):
        domains = {
            "web-svc-cdn": ["cdn.abc.onion", "cdn.example"],
            "web-app-bbb": ["bbb.example"],
        }
        self.assertEqual(
            align_domain_to_consumer(
                domains, "web-svc-cdn", "cdn.abc.onion", consumer="web-app-bbb"
            ),
            "cdn.example",
        )

    def test_align_domain_to_consumer_reads_variables_application_id(self):
        domains = {
            "web-svc-cdn": ["cdn.abc.onion", "cdn.example"],
            "web-app-bbb": ["bbb.example"],
        }
        self.assertEqual(
            align_domain_to_consumer(
                domains,
                "web-svc-cdn",
                "cdn.abc.onion",
                variables={"application_id": "web-app-bbb"},
            ),
            "cdn.example",
        )

    def test_align_domain_to_consumer_onion_consumer_unchanged(self):
        domains = {
            "web-svc-cdn": ["cdn.abc.onion", "cdn.example"],
            "web-app-dash": ["dash.abc.onion"],
        }
        self.assertEqual(
            align_domain_to_consumer(
                domains, "web-svc-cdn", "cdn.abc.onion", consumer="web-app-dash"
            ),
            "cdn.abc.onion",
        )

    def test_align_domain_to_consumer_onion_only_target_falls_back(self):
        domains = {
            "web-svc-cdn": ["cdn.abc.onion"],
            "web-app-bbb": ["bbb.example"],
        }
        self.assertEqual(
            align_domain_to_consumer(
                domains, "web-svc-cdn", "cdn.abc.onion", consumer="web-app-bbb"
            ),
            "cdn.abc.onion",
        )

    def test_align_domain_to_consumer_clearnet_target_untouched(self):
        domains = {
            "web-svc-cdn": ["cdn.example"],
            "web-app-bbb": ["bbb.example"],
        }
        self.assertEqual(
            align_domain_to_consumer(
                domains, "web-svc-cdn", "cdn.example", consumer="web-app-bbb"
            ),
            "cdn.example",
        )

    def test_align_domain_to_consumer_no_or_self_or_unknown_consumer(self):
        domains = {
            "web-svc-cdn": ["cdn.abc.onion", "cdn.example"],
            "web-app-bbb": ["bbb.example"],
        }
        self.assertEqual(
            align_domain_to_consumer(domains, "web-svc-cdn", "cdn.abc.onion"),
            "cdn.abc.onion",
        )
        self.assertEqual(
            align_domain_to_consumer(
                domains, "web-svc-cdn", "cdn.abc.onion", consumer="web-svc-cdn"
            ),
            "cdn.abc.onion",
        )
        self.assertEqual(
            align_domain_to_consumer(
                domains, "web-svc-cdn", "cdn.abc.onion", consumer="svc-db-postgres"
            ),
            "cdn.abc.onion",
        )

    def test_align_domain_to_consumer_templates_consumer(self):
        class _FakeTemplar:
            def template(self, value):
                return {"{{ application_id }}": "web-app-bbb"}.get(value, value)

        domains = {
            "web-svc-cdn": ["cdn.abc.onion", "cdn.example"],
            "web-app-bbb": ["bbb.example"],
        }
        self.assertEqual(
            align_domain_to_consumer(
                domains,
                "web-svc-cdn",
                "cdn.abc.onion",
                variables={"application_id": "{{ application_id }}"},
                templar=_FakeTemplar(),
            ),
            "cdn.example",
        )

    def test_align_domain_to_consumer_dict_target_picks_clearnet_value(self):
        domains = {
            "web-app-matrix": {
                "synapse_onion": "matrix.abc.onion",
                "element_onion": "element.abc.onion",
                "synapse": "matrix.example",
                "element": "element.example",
            },
            "web-app-bbb": ["bbb.example"],
        }
        self.assertEqual(
            align_domain_to_consumer(
                domains, "web-app-matrix", "matrix.abc.onion", consumer="web-app-bbb"
            ),
            "matrix.example",
        )

    def test_resolve_mode_app_level_mode_over_flavor(self):
        # server.tls.mode takes precedence over server.tls.flavor.
        app = {"server": {"tls": {"mode": "self_signed", "flavor": "letsencrypt"}}}
        self.assertEqual(
            resolve_mode(app, True, "letsencrypt", err_prefix="t"), "self_signed"
        )
        # falls back to flavor when mode unset
        app2 = {"server": {"tls": {"flavor": "self_signed"}}}
        self.assertEqual(
            resolve_mode(app2, True, "letsencrypt", err_prefix="t"), "self_signed"
        )

    def test_resolve_le_name(self):
        app = {}
        self.assertEqual(resolve_le_name(app, "x.example"), "x.example")
        app2 = {"server": {"tls": {"letsencrypt_cert_name": "mycert"}}}
        self.assertEqual(resolve_le_name(app2, "x.example"), "mycert")

    def test_override_san_list(self):
        self.assertIsNone(override_san_list({}))
        self.assertEqual(
            override_san_list({"server": {"tls": {"domains_san": "alt.example"}}}),
            ["alt.example"],
        )
        self.assertEqual(
            override_san_list({"server": {"tls": {"domains_san": ["a", "b", ""]}}}),
            ["a", "b"],
        )
        self.assertEqual(
            override_san_list({"server": {"tls": {"domains_san": {"x": "y"}}}}),
            [],
        )

    def test_available_flavors(self):
        self.assertIn("letsencrypt", AVAILABLE_FLAVORS)
        self.assertIn("self_signed", AVAILABLE_FLAVORS)


if __name__ == "__main__":
    unittest.main()
