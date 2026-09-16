from __future__ import annotations

import importlib.util
import sys
import unittest
import unittest.mock as mock
from unittest.mock import patch

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


def _app(service_enabled, domain="filer.example.com"):
    return {
        "server": {"domains": {"canonical": {"filer": domain}}},
        "services": {"filer": {"enabled": service_enabled, "domains": ["filer"]}},
    }


class CspSkipDomainsLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module(
            "roles/sys-ctl-hlth-csp/lookup_plugins/csp_skip_domains.py",
            "csp_skip_domains_lookup",
        )

    def _run(self, applications, **kwargs):
        lm = self.module.LookupModule()
        lm._templar = _DummyTemplar()
        lm._loader = mock.MagicMock()
        with patch.object(self.module, "lookup_loader") as loader_mock:
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [applications]
            )
            return lm.run(terms=[], variables={}, **kwargs)[0]

    def test_empty_applications_returns_empty_list(self):
        self.assertEqual(self._run({}), [])

    def test_non_mapping_applications_returns_empty(self):
        self.assertEqual(self._run([]), [])

    def test_a_disabled_service_hides_its_canonical_domain(self):
        self.assertEqual(
            self._run({"web-app-seaweedfs": _app(False)}),
            ["filer.example.com"],
        )

    def test_an_enabled_service_keeps_its_domain_under_probe(self):
        self.assertEqual(self._run({"web-app-seaweedfs": _app(True)}), [])

    def test_a_service_without_domains_is_ignored(self):
        apps = {
            "web-app-foo": {
                "server": {"domains": {"canonical": {"web": "foo.example.com"}}},
                "services": {"worker": {"enabled": False}},
            }
        }
        self.assertEqual(self._run(apps), [])

    def test_the_selection_filters_which_apps_are_inspected(self):
        apps = {
            "web-app-a": _app(False, "a.example.com"),
            "web-app-b": _app(False, "b.example.com"),
        }
        self.assertEqual(
            self._run(apps, group_names=["web-app-a"]),
            ["a.example.com"],
        )

    def test_group_names_csv_string_is_accepted(self):
        apps = {
            "web-app-a": _app(False, "a.example.com"),
            "web-app-b": _app(False, "b.example.com"),
        }
        self.assertEqual(
            self._run(apps, group_names="web-app-a,web-app-b"),
            ["a.example.com", "b.example.com"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
