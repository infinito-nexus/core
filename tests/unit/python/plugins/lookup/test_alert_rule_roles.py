"""Unit tests for plugins/lookup/alert_rule_roles.py.

Mocks the Ansible-side machinery and asserts the plugin returns exactly the
scraped roles that ship a ``templates/prometheus/alert_rules.yml.j2``.

Activation is delegated to ``native_metrics_apps`` rather than re-derived here,
so these tests stub that lookup and assert the intersection. A role that is
deployed but not scraped must not contribute rules: its alert would fire on
``absent()`` forever.
"""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

import plugins.lookup.alert_rule_roles as module
from plugins.lookup.alert_rule_roles import LookupModule


class _Templar:
    def __init__(self, vars_=None):
        self.available_variables = vars_ or {}

    def template(self, value, **_):
        return value


def _make_lookup(vars_=None):
    lm = LookupModule()
    lm._templar = _Templar(vars_ or {})
    lm._loader = mock.MagicMock()
    return lm


def _seed_roles(tmp_path, roles_with_template, roles_without_template=()):
    for role_id in roles_with_template:
        target = tmp_path / role_id / "templates" / "prometheus"
        target.mkdir(parents=True)
        (target / "alert_rules.yml.j2").write_text("  - name: probe\n")
    for role_id in roles_without_template:
        (tmp_path / role_id / "templates").mkdir(parents=True)


class TestAlertRuleRolesLookup(unittest.TestCase):
    def setUp(self):
        self._roles_dir = mock.patch.object(module, "ROLES_DIR")
        self.roles_dir = self._roles_dir.start()
        self.addCleanup(self._roles_dir.stop)

    def _patch_scraped(self, scraped):
        """Stand in for the native_metrics_apps lookup."""
        inner = mock.MagicMock()
        inner.run.return_value = [list(scraped)]
        loader = mock.patch.object(module, "lookup_loader")
        started = loader.start()
        started.get.return_value = inner
        self.addCleanup(loader.stop)

    def test_raises_when_positional_terms_supplied(self):
        self._patch_scraped([])
        lm = _make_lookup({"group_names": []})
        with self.assertRaises(ValueError):
            lm.run(["unexpected"], variables=lm._templar.available_variables)

    def test_returns_only_scraped_roles_that_ship_a_template(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _seed_roles(
                tmp_path,
                roles_with_template=["web-app-openbao", "svc-db-postgres"],
                roles_without_template=["web-app-matomo"],
            )
            module.ROLES_DIR = tmp_path
            self._patch_scraped(["web-app-matomo", "web-app-openbao"])

            lm = _make_lookup({})
            self.assertEqual(lm.run([], variables={}), [["web-app-openbao"]])

    def test_a_deployed_role_that_is_not_scraped_contributes_no_rules(self):
        """The whole point of moving the filter out of the fragments.

        svc-db-postgres ships a template here but native_metrics_apps does not
        list it, so its rules must not reach the file.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _seed_roles(tmp_path, roles_with_template=["svc-db-postgres"])
            module.ROLES_DIR = tmp_path
            self._patch_scraped([])

            lm = _make_lookup({})
            self.assertEqual(lm.run([], variables={}), [[]])

    def test_result_is_sorted_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _seed_roles(tmp_path, roles_with_template=["b-role", "a-role"])
            module.ROLES_DIR = tmp_path
            self._patch_scraped(["b-role", "a-role", "b-role"])

            lm = _make_lookup({})
            self.assertEqual(lm.run([], variables={}), [["a-role", "b-role"]])

    def test_returns_empty_list_when_nothing_is_scraped(self):
        with tempfile.TemporaryDirectory() as td:
            module.ROLES_DIR = Path(td)
            self._patch_scraped([])

            lm = _make_lookup({})
            self.assertEqual(lm.run([], variables={}), [[]])
