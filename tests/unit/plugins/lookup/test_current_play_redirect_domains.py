from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from plugins.lookup.current_play_redirect_domains import LookupModule


class _DummyTemplar:
    def __init__(self, available_variables=None):
        self.available_variables = available_variables or {}


class CurrentPlayRedirectDomainsLookupTests(unittest.TestCase):
    def _make_lookup(self, variables=None):
        lm = LookupModule()
        lm._templar = _DummyTemplar(variables or {})
        lm._loader = None
        return lm

    def _patch_lookups(self, *, deployed=None, current_play_apps=None):
        def _get(name, *args, **kwargs):
            plugin = MagicMock()
            if name == "deployment":
                plugin.run.return_value = [{"deployed": list(deployed or [])}]
            elif name == "applications_current_play":
                plugin.run.return_value = [current_play_apps or {}]
            else:
                plugin.run.return_value = [None]
            return plugin

        return patch(
            "plugins.lookup.current_play_redirect_domains.lookup_loader.get",
            side_effect=_get,
        )

    def test_empty_inputs_returns_empty_list(self):
        lm = self._make_lookup()
        with self._patch_lookups(deployed=[], current_play_apps={}):
            result = lm.run(terms=[], variables={})[0]
        self.assertEqual(result, [])

    def test_user_redirect_domain_mappings_preserved(self):
        lm = self._make_lookup()
        variables = {
            "redirect_domain_mappings": [
                {"source": "old.example.com", "target": "new.example.com"},
            ],
        }
        with self._patch_lookups(deployed=[], current_play_apps={}):
            result = lm.run(terms=[], variables=variables)[0]
        self.assertEqual(
            result,
            [{"source": "old.example.com", "target": "new.example.com"}],
        )

    def test_primary_redirect_appended_when_rdr_domains_deployed(self):
        lm = self._make_lookup()
        variables = {
            "DOMAIN_PRIMARY": "infinito.example",
            "DOMAIN_HOMEPAGE": "infinito.nexus",
        }
        with self._patch_lookups(
            deployed=["web-opt-rdr-domains"], current_play_apps={}
        ):
            result = lm.run(terms=[], variables=variables)[0]
        self.assertIn(
            {"source": "infinito.example", "target": "infinito.nexus"},
            result,
        )

    def test_primary_redirect_absent_when_rdr_domains_not_deployed(self):
        lm = self._make_lookup()
        variables = {
            "DOMAIN_PRIMARY": "infinito.example",
            "DOMAIN_HOMEPAGE": "infinito.nexus",
        }
        with self._patch_lookups(deployed=["web-opt-rdr-www"], current_play_apps={}):
            result = lm.run(terms=[], variables=variables)[0]
        self.assertEqual(result, [])

    def test_primary_redirect_absent_when_domain_homepage_missing(self):
        lm = self._make_lookup()
        variables = {"DOMAIN_PRIMARY": "infinito.example"}
        with self._patch_lookups(
            deployed=["web-opt-rdr-domains"], current_play_apps={}
        ):
            result = lm.run(terms=[], variables=variables)[0]
        self.assertEqual(result, [])

    def test_per_app_domain_mappings_included(self):
        lm = self._make_lookup()
        apps = {
            "web-app-foo": {
                "server": {
                    "domains": {
                        "canonical": ["foo.example.com"],
                        "aliases": ["alt-foo.example.com"],
                    }
                }
            }
        }
        variables = {
            "DOMAIN_PRIMARY": "example.com",
            "AUTO_BUILD_ALIASES": False,
        }
        with self._patch_lookups(deployed=[], current_play_apps=apps):
            result = lm.run(terms=[], variables=variables)[0]
        self.assertIn(
            {"source": "alt-foo.example.com", "target": "foo.example.com"},
            result,
        )

    def test_user_mapping_overrides_per_app_mapping_on_same_source(self):
        lm = self._make_lookup()
        apps = {
            "web-app-foo": {
                "server": {
                    "domains": {
                        "canonical": ["foo.example.com"],
                        "aliases": ["alt.example.com"],
                    }
                }
            }
        }
        variables = {
            "DOMAIN_PRIMARY": "example.com",
            "AUTO_BUILD_ALIASES": False,
            "redirect_domain_mappings": [
                {"source": "alt.example.com", "target": "OVERRIDE.example.com"},
            ],
        }
        with self._patch_lookups(deployed=[], current_play_apps=apps):
            result = lm.run(terms=[], variables=variables)[0]
        for entry in result:
            if entry["source"] == "alt.example.com":
                self.assertEqual(entry["target"], "OVERRIDE.example.com")
                break
        else:
            self.fail("expected entry with source alt.example.com")

    def test_combined_user_primary_and_per_app(self):
        lm = self._make_lookup()
        apps = {
            "web-app-foo": {
                "server": {
                    "domains": {
                        "canonical": ["foo.example.com"],
                        "aliases": ["alt-foo.example.com"],
                    }
                }
            }
        }
        variables = {
            "DOMAIN_PRIMARY": "infinito.example",
            "DOMAIN_HOMEPAGE": "infinito.nexus",
            "AUTO_BUILD_ALIASES": False,
            "redirect_domain_mappings": [
                {"source": "legacy.example.com", "target": "current.example.com"},
            ],
        }
        with self._patch_lookups(
            deployed=["web-opt-rdr-domains"], current_play_apps=apps
        ):
            result = lm.run(terms=[], variables=variables)[0]
        sources = {entry["source"]: entry["target"] for entry in result}
        self.assertEqual(sources.get("legacy.example.com"), "current.example.com")
        self.assertEqual(sources.get("infinito.example"), "infinito.nexus")
        self.assertEqual(sources.get("alt-foo.example.com"), "foo.example.com")

    def test_non_list_redirect_domain_mappings_treated_as_empty(self):
        lm = self._make_lookup()
        variables = {"redirect_domain_mappings": "not-a-list"}
        with self._patch_lookups(deployed=[], current_play_apps={}):
            result = lm.run(terms=[], variables=variables)[0]
        self.assertEqual(result, [])

    def test_non_mapping_applications_current_play_skipped(self):
        lm = self._make_lookup()
        variables = {
            "DOMAIN_PRIMARY": "infinito.example",
            "DOMAIN_HOMEPAGE": "infinito.nexus",
        }
        with self._patch_lookups(
            deployed=["web-opt-rdr-domains"], current_play_apps=["not", "a", "dict"]
        ):
            result = lm.run(terms=[], variables=variables)[0]
        self.assertEqual(
            result,
            [{"source": "infinito.example", "target": "infinito.nexus"}],
        )

    def test_jinja_tagged_domain_primary_is_templated(self):
        class _ResolvingTemplar:
            def __init__(self, mapping):
                self._mapping = mapping
                self.available_variables = {}
                self.calls = []

            def template(self, value):
                self.calls.append(value)
                return self._mapping.get(value, value)

        lm = LookupModule()
        lm._templar = _ResolvingTemplar(
            {
                "{{ lookup('env','INFINITO_DOMAIN') }}": "infinito.example",
                "{{ lookup('domain','web-app-dashboard') }}": "infinito.nexus",
            }
        )
        lm._loader = None
        variables = {
            "DOMAIN_PRIMARY": "{{ lookup('env','INFINITO_DOMAIN') }}",
            "DOMAIN_HOMEPAGE": "{{ lookup('domain','web-app-dashboard') }}",
        }
        with self._patch_lookups(
            deployed=["web-opt-rdr-domains"], current_play_apps={}
        ):
            result = lm.run(terms=[], variables=variables)[0]

        self.assertEqual(
            result,
            [{"source": "infinito.example", "target": "infinito.nexus"}],
        )
        self.assertIn(
            "{{ lookup('env','INFINITO_DOMAIN') }}",
            lm._templar.calls,
        )

    def test_templar_failure_falls_back_to_raw_value(self):
        class _FailingTemplar:
            def __init__(self):
                self.available_variables = {}

            def template(self, value):
                raise RuntimeError("templar unavailable")

        lm = LookupModule()
        lm._templar = _FailingTemplar()
        lm._loader = None
        variables = {
            "DOMAIN_PRIMARY": "infinito.example",
            "DOMAIN_HOMEPAGE": "infinito.nexus",
        }
        with self._patch_lookups(
            deployed=["web-opt-rdr-domains"], current_play_apps={}
        ):
            result = lm.run(terms=[], variables=variables)[0]
        self.assertEqual(
            result,
            [{"source": "infinito.example", "target": "infinito.nexus"}],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
