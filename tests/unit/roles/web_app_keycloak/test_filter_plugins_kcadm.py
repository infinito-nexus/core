from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles" / "web-app-keycloak"
FILTER_PATH = ROLE_DIR / "filter_plugins" / "kcadm.py"
MODUTILS_PATH = PROJECT_ROOT / "utils" / "kcadm_json.py"


def _load_py_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


class TestFilterPluginKcadm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.filter_mod = _load_py_module(
            "role_web_app_keycloak_filter_kcadm", FILTER_PATH
        )
        cls.modutils_mod = _load_py_module(
            "role_web_app_keycloak_module_utils_kcadm_json", MODUTILS_PATH
        )

    def test_filters_expose_kcadm_json(self):
        fm = self.filter_mod.FilterModule()
        filters = fm.filters()
        self.assertIn("kcadm_json", filters)
        self.assertTrue(callable(filters["kcadm_json"]))

    def test_filter_kcadm_json_parses_noisy_stdout(self):
        fm = self.filter_mod.FilterModule()
        noisy = '[0.001s][warning][os] noise\n[{"id":"abc"},{"id":"def"}]'
        self.assertEqual(fm.kcadm_json(noisy), [{"id": "abc"}, {"id": "def"}])

    def test_filter_loads_role_local_module_utils_from_expected_path(self):
        origin = Path(self.filter_mod._kcadm_json_mod.__file__).resolve()
        self.assertEqual(origin, MODUTILS_PATH.resolve())

    def test_filter_function_behavior_matches_module_utils(self):
        sample = '[0.001s][warning][os] noise\n{"ok": true, "n": 3}'

        fm = self.filter_mod.FilterModule()

        got_filter = fm.kcadm_json(sample)
        got_modutils = self.modutils_mod.json_from_noisy_stdout(sample)

        self.assertEqual(got_filter, got_modutils)

    def test_filter_function_bytecode_matches_module_utils(self):
        self.assertEqual(
            self.filter_mod.json_from_noisy_stdout.__code__.co_code,
            self.modutils_mod.json_from_noisy_stdout.__code__.co_code,
        )


if __name__ == "__main__":
    unittest.main()
