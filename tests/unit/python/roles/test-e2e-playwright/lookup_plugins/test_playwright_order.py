import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.role_tests import LookupModule as RoleTestsLookup
from utils.cache.yaml import dump_yaml
from utils.roles.mapping import ROLE_FILE_META_TESTS

from . import PROJECT_ROOT

ROUND = [
    "web-app-keycloak",
    "web-app-matomo",
    "web-app-docs",
    "web-app-stalwart",
    "web-app-prometheus",
]


def _load_module():
    path = (
        PROJECT_ROOT
        / "roles"
        / "test-e2e-playwright"
        / "lookup_plugins"
        / "playwright_order.py"
    )
    spec = importlib.util.spec_from_file_location("playwright_order_lookup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["playwright_order_lookup"] = module
    spec.loader.exec_module(module)
    return module


_plugin = _load_module()


class TestPlaywrightOrder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="playwright_order_")
        self.addCleanup(self.tmp.cleanup)
        self.playbook_dir = Path(self.tmp.name)
        for role in [*ROUND, "web-app-outside"]:
            (self.playbook_dir / "roles" / role / "meta").mkdir(parents=True)
        self.variables = {
            "playbook_dir": str(self.playbook_dir),
            "invokables": [*ROUND, "web-app-outside"],
        }

    def _declare_run_after(self, role: str, run_after) -> None:
        dump_yaml(
            self.playbook_dir / "roles" / role / ROLE_FILE_META_TESTS,
            {"playwright": {"timeout": 9000, "run_after": run_after}},
        )

    def _order(self, roles: list[str]) -> list[str]:
        templar = Templar(loader=DataLoader(), variables=self.variables)
        lookup = _plugin.LookupModule(loader=DataLoader(), templar=templar)
        role_tests = RoleTestsLookup(loader=DataLoader(), templar=templar)
        with patch.object(_plugin, "lookup_loader") as loader:
            loader.get.return_value = role_tests
            return lookup.run([roles], variables=self.variables)[0]

    def test_without_run_after_the_order_is_kept(self):
        self.assertEqual(self._order(list(ROUND)), ROUND)

    def test_every_invokable_but_itself_puts_docs_behind_all_others(self):
        self._declare_run_after(
            "web-app-docs", "{{ invokables | difference([application_id]) }}"
        )
        others = [role for role in ROUND if role != "web-app-docs"]
        self.assertEqual(self._order(list(ROUND)), [*others, "web-app-docs"])

    def test_run_after_only_constrains_roles_in_the_round(self):
        self._declare_run_after("web-app-matomo", ["web-app-outside"])
        self._declare_run_after("web-app-docs", ["web-app-stalwart"])
        self.assertEqual(
            self._order(list(ROUND)),
            [
                "web-app-keycloak",
                "web-app-matomo",
                "web-app-stalwart",
                "web-app-docs",
                "web-app-prometheus",
            ],
        )

    def test_a_role_naming_itself_raises(self):
        self._declare_run_after("web-app-docs", ["web-app-docs"])
        with self.assertRaises(AnsibleError):
            self._order(list(ROUND))

    def test_a_cycle_raises(self):
        self._declare_run_after("web-app-docs", ["web-app-prometheus"])
        self._declare_run_after("web-app-prometheus", ["web-app-docs"])
        with self.assertRaises(AnsibleError):
            self._order(list(ROUND))

    def test_an_unknown_role_raises(self):
        self._declare_run_after("web-app-docs", ["web-app-typo"])
        with self.assertRaises(AnsibleError):
            self._order(list(ROUND))

    def test_a_value_that_is_no_list_raises(self):
        self._declare_run_after("web-app-docs", "web-app-stalwart")
        with self.assertRaises(AnsibleError):
            self._order(list(ROUND))


if __name__ == "__main__":
    unittest.main()
