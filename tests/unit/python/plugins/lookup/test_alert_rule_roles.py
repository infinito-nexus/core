"""Unit tests for plugins/lookup/alert_rule_roles.py.

Mocks the Ansible-side machinery and asserts the plugin returns exactly the
deployed roles that ship a ``templates/prometheus/alert_rules.yml.j2``.
"""

from __future__ import annotations

import unittest
import unittest.mock as mock

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
        self._tmp = mock.patch.object(module, "ROLES_DIR")
        self.roles_dir = self._tmp.start()
        self.addCleanup(self._tmp.stop)

    def test_raises_when_positional_terms_supplied(self):
        lm = _make_lookup({"group_names": []})
        with self.assertRaises(ValueError):
            lm.run(["unexpected"], variables=lm._templar.available_variables)

    def test_returns_only_deployed_roles_that_ship_a_template(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _seed_roles(
                tmp_path,
                roles_with_template=["web-app-openbao", "svc-db-postgres"],
                roles_without_template=["web-app-matomo"],
            )
            module.ROLES_DIR = tmp_path

            vars_ = {
                "group_names": [
                    "web-app-matomo",
                    "web-app-openbao",
                    "web-app-never-deployed",
                ]
            }
            lm = _make_lookup(vars_)
            self.assertEqual(lm.run([], variables=vars_), [["web-app-openbao"]])

    def test_result_is_sorted_and_deduplicated(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _seed_roles(tmp_path, roles_with_template=["b-role", "a-role"])
            module.ROLES_DIR = tmp_path

            vars_ = {"group_names": ["b-role", "a-role", "b-role"]}
            lm = _make_lookup(vars_)
            self.assertEqual(lm.run([], variables=vars_), [["a-role", "b-role"]])

    def test_returns_empty_list_without_group_names(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            module.ROLES_DIR = Path(td)
            lm = _make_lookup({})
            self.assertEqual(lm.run([], variables={}), [[]])
