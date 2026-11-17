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
    "roles/web-app-wordpress/filter_plugins/keycloak_user_id.py", "keycloak_user_id"
)
JVM_WARNINGS = (
    (
        "[0.001s][warning][os,container] Cgroup memory controller path at "
        "'/sys/fs/cgroup' seems not to be accurate, detected limits won't be accurate"
    ),
    (
        "[0.002s][warning][os,container] Cgroup cpu controller path at "
        "'/sys/fs/cgroup' seems not to be accurate"
    ),
)


def _pick(users, username="platformadmin"):
    return MODULE.keycloak_user_id(json.dumps(users), username)


class TestKeycloakUserId(unittest.TestCase):
    def test_the_user_with_the_exact_name_is_picked_among_look_alikes(self):
        users = [
            {"id": "id-2", "username": "platformadmin2"},
            {"id": "id-1", "username": "platformadmin"},
        ]
        self.assertEqual(_pick(users), "id-1")

    def test_the_name_matches_regardless_of_case(self):
        self.assertEqual(
            _pick([{"id": "id-1", "username": "platformadmin"}], "PlatformAdmin"),
            "id-1",
        )

    def test_a_missing_user_is_refused(self):
        with self.assertRaisesRegex(AnsibleFilterError, "found 0"):
            _pick([{"id": "id-2", "username": "platformadmin2"}])

    def test_two_users_with_the_name_are_refused(self):
        with self.assertRaisesRegex(AnsibleFilterError, "found 2"):
            _pick(
                [
                    {"id": "id-1", "username": "platformadmin"},
                    {"id": "id-3", "username": "PlatformAdmin"},
                ]
            )

    def test_a_user_without_an_id_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            _pick([{"id": "", "username": "platformadmin"}])

    def test_jvm_warnings_before_the_list_are_skipped(self):
        users = [
            {"id": "id-2", "username": "platformadmin2"},
            {"id": "id-1", "username": "platformadmin"},
        ]
        stdout = "\n".join([*JVM_WARNINGS, json.dumps(users)])
        self.assertEqual(MODULE.keycloak_user_id(stdout, "platformadmin"), "id-1")

    def test_output_that_is_no_json_list_is_refused(self):
        for stdout in (
            "Logging into http://127.0.0.1:8080",
            json.dumps({"id": "id-1"}),
        ):
            with self.subTest(stdout=stdout), self.assertRaises(AnsibleFilterError):
                MODULE.keycloak_user_id(stdout, "platformadmin")


if __name__ == "__main__":
    unittest.main()
