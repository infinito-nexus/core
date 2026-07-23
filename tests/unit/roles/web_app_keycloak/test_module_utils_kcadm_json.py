from __future__ import annotations

import importlib.util
import unittest
from typing import TYPE_CHECKING

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLE_DIR = PROJECT_ROOT / "roles" / "web-app-keycloak"
MOD_PATH = PROJECT_ROOT / "utils" / "kcadm_json.py"


def _load_py_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_kcadm_json = _load_py_module("role_web_app_keycloak_module_utils_kcadm_json", MOD_PATH)
json_from_noisy_stdout = _kcadm_json.json_from_noisy_stdout


class TestJsonFromNoisyStdout(unittest.TestCase):
    def test_parses_pure_object(self):
        self.assertEqual(
            json_from_noisy_stdout('{"a": 1, "b": "x"}'), {"a": 1, "b": "x"}
        )

    def test_parses_pure_array(self):
        self.assertEqual(
            json_from_noisy_stdout('[{"id":"1"},{"id":"2"}]'),
            [{"id": "1"}, {"id": "2"}],
        )

    def test_parses_with_leading_noise_then_object(self):
        noisy = '[0.001s][warning][os] something something\nJava HotSpot(TM) warning blah\n{"ok": true, "n": 3}'
        self.assertEqual(json_from_noisy_stdout(noisy), {"ok": True, "n": 3})

    def test_parses_with_leading_noise_then_array(self):
        noisy = '[0.001s][warning][os] something something\n[0.002s][warning][gc] other warning\n[{"name":"a"},{"name":"b"}]'
        self.assertEqual(json_from_noisy_stdout(noisy), [{"name": "a"}, {"name": "b"}])

    def test_raises_on_none(self):
        with self.assertRaises(ValueError):
            json_from_noisy_stdout(None)

    def test_raises_on_empty(self):
        with self.assertRaises(ValueError):
            json_from_noisy_stdout("   \n\t  ")

    def test_raises_when_no_json_delimiters(self):
        with self.assertRaises(ValueError):
            json_from_noisy_stdout("no json here, just text")

    def test_raises_when_candidates_exist_but_invalid_json(self):
        noisy = "[0.001s][warning] definitely not json\n{not: json}"
        with self.assertRaises(ValueError):
            json_from_noisy_stdout(noisy)


if __name__ == "__main__":
    unittest.main()
