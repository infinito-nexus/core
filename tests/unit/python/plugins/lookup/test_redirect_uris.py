from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.redirect_uris import LookupModule, build_redirect_uris

SSO = {"services": {"sso": {"enabled": True}}}
KEYCLOAK_FLAG = "{{ 'web-app-keycloak' in group_names }}"
TLS_FLAG = "{{ APP_TLS }}"


class _FirstStr(str):
    __slots__ = ()


class _SecondStr(str):
    __slots__ = ()


class _Stub:
    def __init__(self, payload):
        self.payload = payload

    def run(self, terms, variables=None, **kwargs):
        return [self.payload]


def _run(lookup, domains, applications, variables):
    payloads = {"domains": _Stub(domains), "applications": _Stub(applications)}
    with mock.patch(
        "plugins.lookup.redirect_uris.lookup_loader.get",
        side_effect=lambda name, **kwargs: payloads[name],
    ):
        return lookup.run([], variables=variables)


class TestBuildRedirectUris(unittest.TestCase):
    def test_single_domain(self):
        result = build_redirect_uris({"app1": "example.org"}, {"app1": SSO}, True)
        self.assertEqual(result, ["https://example.org/*"])

    def test_multiple_domains(self):
        result = build_redirect_uris(
            {"appX": ["a.example.org", "b.example.org"]}, {"appX": SSO}, True
        )
        self.assertCountEqual(
            result, ["https://a.example.org/*", "https://b.example.org/*"]
        )

    def test_onion_domain_stays_plaintext(self):
        domains = {"clear": "app.example.org", "hidden": "abcdefghijklmnop.onion"}
        result = build_redirect_uris(domains, {"clear": SSO, "hidden": SSO}, True)
        self.assertCountEqual(
            result, ["https://app.example.org/*", "http://abcdefghijklmnop.onion/*"]
        )

    def test_per_app_tls_override_wins_over_the_global_default(self):
        domains = {"secure": "a.example.org", "plain": "b.example.org"}
        applications = {
            "secure": SSO,
            "plain": {**SSO, "server": {"tls": {"enabled": False}}},
        }
        result = build_redirect_uris(domains, applications, True)
        self.assertCountEqual(
            result, ["https://a.example.org/*", "http://b.example.org/*"]
        )

    def test_global_default_off_yields_plaintext(self):
        result = build_redirect_uris({"app1": "example.org"}, {"app1": SSO}, False)
        self.assertEqual(result, ["http://example.org/*"])

    def test_feature_missing_is_skipped(self):
        applications = {"app1": {"features": {"oauth2": False, "oidc": False}}}
        self.assertEqual(
            build_redirect_uris({"app1": "example.org"}, applications, True), []
        )

    def test_wildcard_customization(self):
        result = build_redirect_uris(
            {"app1": "x.test"}, {"app1": SSO}, False, wildcard="/cb"
        )
        self.assertEqual(result, ["http://x.test/cb"])

    def test_dedup_default_true(self):
        domains = {"app1": ["dup.test", "dup.test", "other.test"]}
        result = build_redirect_uris(domains, {"app1": SSO}, True)
        self.assertEqual(result, ["https://dup.test/*", "https://other.test/*"])

    def test_dedup_false_keeps_duplicates(self):
        domains = {"app1": ["dup.test", "dup.test"]}
        result = build_redirect_uris(domains, {"app1": SSO}, True, dedup=False)
        self.assertEqual(result, ["https://dup.test/*", "https://dup.test/*"])

    def test_nested_domain_mapping_is_flattened(self):
        domains = {
            "app1": {
                "primary": "a.example.org",
                "nested": {"x": "b.example.org", "y": ["c.example.org"]},
            }
        }
        result = build_redirect_uris(domains, {"app1": SSO}, True)
        self.assertEqual(
            result,
            [
                "https://a.example.org/*",
                "https://b.example.org/*",
                "https://c.example.org/*",
            ],
        )

    def test_only_deployed_consumers_are_registered(self):
        domains = {"deployed": "a.example.org", "parked": "b.example.org"}
        result = build_redirect_uris(
            domains, {"deployed": SSO, "parked": SSO}, True, deployed=["deployed"]
        )
        self.assertEqual(result, ["https://a.example.org/*"])

    def test_no_deployment_scope_registers_every_consumer(self):
        domains = {"one": "a.example.org", "two": "b.example.org"}
        result = build_redirect_uris(domains, {"one": SSO, "two": SSO}, True)
        self.assertEqual(result, ["https://a.example.org/*", "https://b.example.org/*"])

    def test_invalid_domains_type_raises(self):
        with self.assertRaises(AnsibleError):
            build_redirect_uris(["not-a-dict"], {}, True)  # type: ignore[arg-type]

    def test_invalid_domain_value_raises(self):
        with self.assertRaises(AnsibleError):
            build_redirect_uris({"app1": 42}, {"app1": SSO}, True)

    def test_a_rendered_view_is_never_rendered_again(self):
        def refuse(value):
            raise AssertionError(f"rendered {value!r}")

        applications = {"app1": {**SSO, "server": {"tls": {"enabled": False}}}}
        result = build_redirect_uris(
            {"app1": "example.org"}, applications, True, render=refuse
        )
        self.assertEqual(result, ["http://example.org/*"])

    def test_a_template_text_renders_once_per_call(self):
        rendered = []

        def render(value):
            rendered.append(value)
            return True

        flags = [KEYCLOAK_FLAG[:1] + KEYCLOAK_FLAG[1:] for _ in range(2)]
        overrides = [TLS_FLAG[:1] + TLS_FLAG[1:] for _ in range(2)]
        self.assertIsNot(flags[0], flags[1])
        self.assertIsNot(overrides[0], overrides[1])
        result = build_redirect_uris(
            {"one": "a.example.org", "two": "b.example.org"},
            {
                app_id: {
                    "services": {"sso": {"enabled": flag}},
                    "server": {"tls": {"enabled": override}},
                }
                for app_id, flag, override in zip(
                    ("one", "two"), flags, overrides, strict=True
                )
            },
            True,
            render=render,
        )
        self.assertEqual(
            (result, rendered),
            (
                ["https://a.example.org/*", "https://b.example.org/*"],
                [KEYCLOAK_FLAG, TLS_FLAG],
            ),
        )

    def test_equal_texts_of_two_str_types_render_apart(self):
        result = build_redirect_uris(
            {"first": "a.example.org", "second": "b.example.org"},
            {
                "first": {"services": {"sso": {"enabled": _FirstStr(KEYCLOAK_FLAG)}}},
                "second": {"services": {"sso": {"enabled": _SecondStr(KEYCLOAK_FLAG)}}},
            },
            True,
            render=lambda value: isinstance(value, _SecondStr),
        )
        self.assertEqual(result, ["https://b.example.org/*"])

    def test_each_template_text_renders_with_its_own_result(self):
        verdicts = {"{{ on }}": True, "{{ off }}": False}
        result = build_redirect_uris(
            {"on": "a.example.org", "off": "b.example.org"},
            {
                "on": {"services": {"sso": {"enabled": "{{ on }}"}}},
                "off": {"services": {"sso": {"enabled": "{{ off }}"}}},
            },
            True,
            render=verdicts.__getitem__,
        )
        self.assertEqual(result, ["https://a.example.org/*"])

    def test_a_flag_that_is_no_template_text_never_reaches_the_render(self):
        def refuse(value):
            raise AssertionError(f"rendered {value!r}")

        flags = {
            "listed": ["x"],
            "unlisted": [],
            "mapped": {"x": 1},
            "yes": True,
            "no": False,
        }
        result = build_redirect_uris(
            {app_id: f"{app_id}.example.org" for app_id in flags},
            {
                app_id: {"services": {"sso": {"enabled": flag}}}
                for app_id, flag in flags.items()
            },
            True,
            render=refuse,
        )
        self.assertEqual(
            result,
            [
                "https://listed.example.org/*",
                "https://mapped.example.org/*",
                "https://yes.example.org/*",
            ],
        )


class TestRedirectUrisLookup(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup = LookupModule()
        self.lookup._templar = None

    def test_terms_raise(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["x"], variables={"TLS_ENABLED": True})

    def test_missing_tls_enabled_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run([], variables={})

    def test_missing_group_names_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run([], variables={"TLS_ENABLED": True})

    def test_group_names_scope_the_registered_consumers(self):
        result = _run(
            self.lookup,
            {"deployed": "a.example.org", "parked": "b.example.org"},
            {"deployed": SSO, "parked": SSO},
            {"TLS_ENABLED": True, "group_names": ["deployed"]},
        )
        self.assertEqual(result, [["https://a.example.org/*"]])

    def test_a_templated_flag_that_renders_false_registers_nothing(self):
        self.lookup._templar = Templar(loader=DataLoader())
        result = _run(
            self.lookup,
            {"on": "a.example.org", "off": "b.example.org"},
            {"on": SSO, "off": {"services": {"sso": {"enabled": KEYCLOAK_FLAG}}}},
            {"TLS_ENABLED": True, "group_names": ["on", "off"]},
        )
        self.assertEqual(result, [["https://a.example.org/*"]])

    def test_a_templated_tls_override_decides_the_scheme(self):
        self.lookup._templar = Templar(loader=DataLoader())
        result = _run(
            self.lookup,
            {"app": "a.example.org"},
            {"app": {**SSO, "server": {"tls": {"enabled": "{{ APP_TLS }}"}}}},
            {"TLS_ENABLED": True, "group_names": ["app"], "APP_TLS": False},
        )
        self.assertEqual(result, [["http://a.example.org/*"]])

    def test_a_flag_renders_against_the_scope_of_each_lookup_call(self):
        self.lookup._templar = Templar(loader=DataLoader())
        flag = {"services": {"sso": {"enabled": "{{ application_id == 'x' }}"}}}
        results = [
            _run(
                self.lookup,
                {"x": "x.example.org", "y": "y.example.org"},
                {"x": flag, "y": flag},
                {
                    "TLS_ENABLED": True,
                    "group_names": ["x", "y"],
                    "application_id": scope,
                },
            )
            for scope in ("x", "y")
        ]
        self.assertEqual(
            results, [[["https://x.example.org/*", "https://y.example.org/*"]], [[]]]
        )

    def test_a_flag_that_stays_template_text_raises(self):
        with self.assertRaises(AnsibleError):
            _run(
                self.lookup,
                {"app": "a.example.org"},
                {"app": {"services": {"sso": {"enabled": KEYCLOAK_FLAG}}}},
                {"TLS_ENABLED": True, "group_names": ["app"]},
            )


if __name__ == "__main__":
    unittest.main()
