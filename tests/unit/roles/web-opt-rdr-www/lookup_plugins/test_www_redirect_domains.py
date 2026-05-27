from __future__ import annotations

import importlib.util
import sys
import unittest
from unittest.mock import MagicMock, patch

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class _DummyTemplar:
    def __init__(self, available_variables: dict | None = None):
        self.available_variables = available_variables or {}


class WwwRedirectDomainsLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module(
            "roles/web-opt-rdr-www/lookup_plugins/www_redirect_domains.py",
            "www_redirect_domains_lookup",
        )
        # Rebind possibly globally-mocked names to the real implementations
        # so this suite is robust against test ordering / pollution.
        from utils.roles.applications.config import get as _real_get

        cls.module.get = _real_get

    def _run(self, applications, variables=None, role_canonical=None, **kwargs):
        lm = self.module.LookupModule()
        lm._templar = _DummyTemplar(variables or {})

        domain_plugin = MagicMock()
        domain_plugin.run.return_value = [role_canonical or ""]

        with (
            patch.object(
                self.module, "get_merged_applications", return_value=applications
            ),
            patch.object(self.module.lookup_loader, "get", return_value=domain_plugin),
        ):
            return lm.run(terms=[], variables=variables or {}, **kwargs)[0]

    def test_empty_applications_returns_empty_list(self):
        self.assertEqual(self._run({}), [])

    def test_canonical_gets_www_prefix(self):
        apps = {
            "web-app-foo": {"server": {"domains": {"canonical": ["foo.example.com"]}}}
        }
        self.assertEqual(
            self._run(apps),
            [{"source": "www.foo.example.com", "target": "foo.example.com"}],
        )

    def test_already_www_prefixed_alias_targets_bare_form(self):
        apps = {
            "web-opt-rdr-www": {
                "server": {
                    "domains": {
                        "canonical": ["w3redirect.example.com"],
                        "aliases": ["www.example.com"],
                    }
                }
            }
        }
        self.assertEqual(
            self._run(apps),
            [
                {"source": "www.example.com", "target": "example.com"},
                {
                    "source": "www.w3redirect.example.com",
                    "target": "w3redirect.example.com",
                },
            ],
        )

    def test_aliases_without_www_get_prefix(self):
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
        self.assertEqual(
            self._run(apps),
            [
                {"source": "www.alt.example.com", "target": "alt.example.com"},
                {"source": "www.foo.example.com", "target": "foo.example.com"},
            ],
        )

    def test_group_names_selection_filters_apps(self):
        apps = {
            "web-app-foo": {"server": {"domains": {"canonical": ["foo.example.com"]}}},
            "web-app-bar": {"server": {"domains": {"canonical": ["bar.example.com"]}}},
        }
        self.assertEqual(
            self._run(apps, group_names=["web-app-foo"]),
            [{"source": "www.foo.example.com", "target": "foo.example.com"}],
        )

    def test_group_names_csv_string_accepted(self):
        apps = {
            "a": {"server": {"domains": {"canonical": ["a.example.com"]}}},
            "b": {"server": {"domains": {"canonical": ["b.example.com"]}}},
            "c": {"server": {"domains": {"canonical": ["c.example.com"]}}},
        }
        self.assertEqual(
            self._run(apps, group_names="a, c"),
            [
                {"source": "www.a.example.com", "target": "a.example.com"},
                {"source": "www.c.example.com", "target": "c.example.com"},
            ],
        )

    def test_dedupes_when_same_mapping_appears_twice(self):
        apps = {
            "x": {
                "server": {
                    "domains": {
                        "canonical": ["x.example.com"],
                        "aliases": ["www.x.example.com"],
                    }
                }
            }
        }
        self.assertEqual(
            self._run(apps),
            [{"source": "www.x.example.com", "target": "x.example.com"}],
        )

    def test_empty_string_canonical_is_ignored(self):
        apps = {"x": {"server": {"domains": {"canonical": ["", "valid.example.com"]}}}}
        self.assertEqual(
            self._run(apps),
            [{"source": "www.valid.example.com", "target": "valid.example.com"}],
        )

    def test_non_mapping_applications_returns_empty(self):
        self.assertEqual(self._run([]), [])

    def test_role_canonical_mapping_appended_via_domain_lookup(self):
        apps = {
            "web-opt-rdr-www": {
                "server": {
                    "domains": {
                        "canonical": ["w3redirect.example.com"],
                        "aliases": ["www.example.com"],
                    }
                }
            }
        }
        result = self._run(
            apps,
            variables={"DOMAIN_HOMEPAGE": "infinito.nexus"},
            role_canonical="w3redirect.example.com",
        )
        self.assertIn(
            {"source": "w3redirect.example.com", "target": "infinito.nexus"},
            result,
        )

    def test_role_mapping_absent_when_domain_homepage_missing(self):
        apps = {
            "web-opt-rdr-www": {
                "server": {"domains": {"canonical": ["w3redirect.example.com"]}}
            }
        }
        result = self._run(apps, role_canonical="w3redirect.example.com")
        sources = [m["source"] for m in result]
        self.assertNotIn("w3redirect.example.com", sources)

    def test_role_mapping_absent_when_role_not_deployed(self):
        apps = {
            "web-app-foo": {"server": {"domains": {"canonical": ["foo.example.com"]}}}
        }
        result = self._run(
            apps,
            variables={"DOMAIN_HOMEPAGE": "infinito.nexus"},
            role_canonical="w3redirect.example.com",
        )
        sources = [m["source"] for m in result]
        self.assertNotIn("w3redirect.example.com", sources)

    def test_role_mapping_not_duplicated(self):
        apps = {
            "web-opt-rdr-www": {
                "server": {"domains": {"canonical": ["w3redirect.example.com"]}}
            }
        }
        result = self._run(
            apps,
            variables={"DOMAIN_HOMEPAGE": "infinito.nexus"},
            role_canonical="w3redirect.example.com",
        )
        keys = [(m["source"], m["target"]) for m in result]
        self.assertEqual(keys.count(("w3redirect.example.com", "infinito.nexus")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
