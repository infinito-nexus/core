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
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_TESTS, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT


def _load_module():
    path = (
        PROJECT_ROOT
        / "roles"
        / "test-e2e-playwright"
        / "lookup_plugins"
        / "playwright_parallel.py"
    )
    spec = importlib.util.spec_from_file_location("playwright_parallel_lookup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["playwright_parallel_lookup"] = module
    spec.loader.exec_module(module)
    return module


_plugin = _load_module()


def declared_caps() -> dict:
    """Collect every role's ``playwright.parallel`` entry.

    Returns:
        The declared value per role name, for the roles that declare one.
    """
    found = {}
    for role in sorted(
        path for path in (PROJECT_ROOT / "roles").iterdir() if path.is_dir()
    ):
        playwright = (
            load_yaml_any(str(role / ROLE_FILE_META_TESTS), default_if_missing={}) or {}
        ).get("playwright") or {}
        if "parallel" in playwright:
            found[role.name] = playwright["parallel"]
    return found


class TestRowCap(unittest.TestCase):
    def test_an_app_without_the_list_runs_one_container(self):
        self.assertEqual(_plugin.row_cap("web-app-x", None, 0), 1)

    def test_the_entry_of_the_round_variant_is_the_cap(self):
        self.assertEqual(_plugin.row_cap("web-app-x", [3, 1, 2], 2), 2)

    def test_a_round_beyond_the_declared_variants_runs_serially(self):
        self.assertEqual(_plugin.row_cap("web-app-x", [3], 1), 1)
        self.assertEqual(_plugin.row_cap("web-app-x", [3], 3), 1)

    def test_a_non_positive_or_non_integer_entry_is_rejected(self):
        for caps in ([0], [-1], ["3"], [True], 3, {"0": 3}):
            with self.subTest(caps=caps), self.assertRaises(AnsibleError):
                _plugin.validate_caps("web-app-x", caps)


class TestPlaywrightParallelLookup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="playwright_parallel_")
        self.addCleanup(self.tmp.cleanup)
        self.playbook_dir = Path(self.tmp.name)
        for role in ("web-app-a", "web-app-b", "web-app-c"):
            (self.playbook_dir / "roles" / role / "meta").mkdir(parents=True)
        dump_yaml(
            self.playbook_dir / "roles" / "web-app-a" / ROLE_FILE_META_TESTS,
            {"playwright": {"parallel": [3, 1]}},
        )
        dump_yaml(
            self.playbook_dir / "roles" / "web-app-b" / ROLE_FILE_META_TESTS,
            {"playwright": {"parallel": [2, 4]}},
        )

    def _cap(self, primary_apps, variant, playbook_dir=None) -> int:
        variables = {
            "playbook_dir": str(playbook_dir or self.playbook_dir),
            "PRIMARY_APPS": primary_apps,
            "VARIANT_INDEX": variant,
        }
        templar = Templar(loader=DataLoader(), variables=variables)
        lookup = _plugin.LookupModule(loader=DataLoader(), templar=templar)
        role_tests = RoleTestsLookup(loader=DataLoader(), templar=templar)
        with patch.object(_plugin, "lookup_loader") as loader:
            loader.get.return_value = role_tests
            return lookup.run([], variables=variables)[0]

    def test_a_round_without_primary_apps_runs_one_container(self):
        self.assertEqual(self._cap([], 0), 1)

    def test_the_primary_app_row_sets_the_cap(self):
        self.assertEqual(self._cap(["web-app-a"], 0), 3)
        self.assertEqual(self._cap(["web-app-a"], 1), 1)

    def test_a_primary_app_that_did_not_opt_in_keeps_the_round_serial(self):
        self.assertEqual(self._cap(["web-app-a", "web-app-c"], 0), 1)

    def test_several_primary_apps_take_the_smallest_cap(self):
        self.assertEqual(self._cap(["web-app-a", "web-app-b"], 0), 2)
        self.assertEqual(self._cap(["web-app-a", "web-app-b"], 1), 1)

    def test_the_cli_string_form_of_primary_apps_opts_the_row_in(self):
        self.assertEqual(self._cap('["web-app-a"]', "0"), 3)
        self.assertEqual(self._cap('["web-app-wordpress"]', "0", PROJECT_ROOT), 3)
        self.assertEqual(self._cap("[]", "0"), 1)

    def test_a_primary_apps_value_that_is_no_list_warns_and_keeps_the_round_serial(
        self,
    ):
        for value in ("web-app-a", '"web-app-a"', '{"a": 1}', "[1]"):
            with self.subTest(value=value), patch.object(_plugin, "Display") as display:
                self.assertEqual(self._cap(value, "0"), 1)
                display.return_value.warning.assert_called_once()

    def test_a_multi_app_round_beyond_a_primary_variants_runs_serially(self):
        for variant in ("1", "2", "3"):
            with self.subTest(variant=variant):
                self.assertEqual(
                    self._cap(
                        '["web-app-wordpress","web-app-nextcloud"]',
                        variant,
                        PROJECT_ROOT,
                    ),
                    1,
                )
        self.assertEqual(self._cap('["web-app-a","web-app-b"]', "5"), 1)

    def test_a_malformed_cap_list_warns_and_keeps_the_round_serial(self):
        dump_yaml(
            self.playbook_dir / "roles" / "web-app-c" / ROLE_FILE_META_TESTS,
            {"playwright": {"parallel": "3"}},
        )
        with patch.object(_plugin, "Display") as display:
            self.assertEqual(self._cap(["web-app-c"], 0), 1)
            display.return_value.warning.assert_called_once()

    def test_every_declared_cap_list_is_valid_and_covers_every_variant(self):
        for role, caps in declared_caps().items():
            with self.subTest(role=role):
                _plugin.validate_caps(role, caps)
                variants = load_yaml_any(
                    str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_VARIANTS),
                    default_if_missing=[{}],
                )
                self.assertEqual(len(caps), len(variants))

    def test_the_sizing_terms_follow_playwright_workers(self):
        lookup = _plugin.LookupModule(
            loader=DataLoader(), templar=Templar(loader=DataLoader())
        )
        self.assertEqual(lookup.run(["memory_mb"], workers="1"), [1536])
        self.assertEqual(lookup.run(["memory_mb"], workers=2), [3072])
        self.assertEqual(lookup.run(["ram_fraction"]), [0.5])
        self.assertEqual(lookup.run(["onion_cap"]), [3])

    def test_wordpress_opts_in_its_first_row_only(self):
        self.assertEqual(self._cap(["web-app-wordpress"], 0, PROJECT_ROOT), 3)
        self.assertEqual(self._cap(["web-app-wordpress"], 1, PROJECT_ROOT), 1)
        self.assertEqual(self._cap(["web-app-wordpress"], 2, PROJECT_ROOT), 1)

    def test_every_other_role_keeps_the_serial_runner(self):
        self.assertEqual(sorted(declared_caps()), ["web-app-wordpress"])


if __name__ == "__main__":
    unittest.main()
