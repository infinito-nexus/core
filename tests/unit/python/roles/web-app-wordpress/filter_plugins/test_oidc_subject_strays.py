from __future__ import annotations

import importlib.util
import json
import sys
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODULE = _load_module(
    "roles/web-app-wordpress/filter_plugins/oidc_subject_strays.py",
    "oidc_subject_strays",
)
KEY = "openid-connect-generic-subject-identity"
SUBJECT = "6f1c0d3e-8b5a-4f0e-9d2c-1a7b3c5e9f00"
OTHER = "0d9e8f7a-6b5c-4d3e-2f1a-0b9c8d7e6f5a"
MALLORY = {"ID": 7, "user_login": "mallory"}
EVE = {"ID": 9, "user_login": "eve"}


def _result(holder: dict, rows) -> dict:
    stdout = (
        rows
        if isinstance(rows, str)
        else json.dumps([{"meta_key": k, "meta_value": v} for k, v in rows])
    )
    return {"item": {"item": holder}, "stdout": stdout}


class TestOidcSubjectStrays(unittest.TestCase):
    def test_every_key_holding_the_subject_is_paired_with_its_holder(self):
        results = [
            _result(MALLORY, [(KEY, SUBJECT), ("wp_" + KEY, OTHER)]),
            _result(EVE, [("wp_2_" + KEY, SUBJECT)]),
        ]
        self.assertEqual(
            MODULE.oidc_subject_strays(results, SUBJECT),
            [
                {"ID": 7, "user_login": "mallory", "meta_key": KEY},
                {"ID": 9, "user_login": "eve", "meta_key": "wp_2_" + KEY},
            ],
        )

    def test_a_key_outside_the_subject_identity_family_is_left_alone(self):
        results = [
            _result(MALLORY, [(KEY + "-backup", SUBJECT), ("nickname", SUBJECT)])
        ]
        self.assertEqual(MODULE.oidc_subject_strays(results, SUBJECT), [])

    def test_no_holder_yields_nothing(self):
        self.assertEqual(MODULE.oidc_subject_strays([], SUBJECT), [])

    def test_output_that_is_no_json_list_fails(self):
        for stdout in ("Warning: something", '{"meta_key": "x"}'):
            with self.subTest(stdout=stdout), self.assertRaises(AnsibleFilterError):
                MODULE.oidc_subject_strays([_result(MALLORY, stdout)], SUBJECT)


if __name__ == "__main__":
    unittest.main()
