from __future__ import annotations

import importlib.util
import sys
import unittest
from unittest import mock
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

    def test_app_with_status_code_ge_400_skips_canonical_and_aliases(self):
        apps = {
            "web-app-bridgy": {
                "domains": {
                    "canonical": ["bridgy.example.com"],
                    "aliases": ["fed.example.com"],
                },
                "server": {
                    "status_codes": {"default": [200, 404]},
                },
            }
        }
        self.assertEqual(self._run(apps), ["bridgy.example.com", "fed.example.com"])

    def test_app_without_status_code_ge_400_is_not_skipped(self):
        apps = {
            "web-app-foo": {
                "domains": {"canonical": ["foo.example.com"]},
                "server": {
                    "status_codes": {"default": [200]},
                },
            }
        }
        self.assertEqual(self._run(apps), [])

    def test_app_without_status_codes_field_is_not_skipped(self):
        apps = {"web-app-foo": {"domains": {"canonical": ["foo.example.com"]}}}
        self.assertEqual(self._run(apps), [])

    def test_group_names_selection_filters_apps(self):
        apps = {
            "web-app-bridgy": {
                "domains": {"canonical": ["bridgy.example.com"]},
                "server": {
                    "status_codes": {"default": [404]},
                },
            },
            "web-app-other": {
                "domains": {"canonical": ["other.example.com"]},
                "server": {
                    "status_codes": {"default": [404]},
                },
            },
        }
        self.assertEqual(
            self._run(apps, group_names=["web-app-bridgy"]),
            ["bridgy.example.com"],
        )

    def test_group_names_csv_string_is_accepted(self):
        apps = {
            "a": {
                "domains": {"canonical": ["a.example.com"]},
                "server": {
                    "status_codes": {"default": [404]},
                },
            },
            "b": {
                "domains": {"canonical": ["b.example.com"]},
                "server": {
                    "status_codes": {"default": [404]},
                },
            },
        }
        self.assertEqual(
            self._run(apps, group_names="a,b"),
            ["a.example.com", "b.example.com"],
        )

    def test_non_4xx_codes_dont_count(self):
        apps = {
            "web-app-foo": {
                "domains": {"canonical": ["foo.example.com"]},
                "server": {
                    "status_codes": {"default": [200, 301, 302]},
                },
            }
        }
        self.assertEqual(self._run(apps), [])

    def test_non_mapping_applications_returns_empty(self):
        self.assertEqual(self._run([]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
