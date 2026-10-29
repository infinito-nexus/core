from __future__ import annotations

import importlib.util
import json
import sys
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _load_module():
    path = (
        PROJECT_ROOT
        / "roles/web-app-nextcloud/filter_plugins/nextcloud_oauth_client.py"
    )
    spec = importlib.util.spec_from_file_location("nextcloud_oauth_client", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["nextcloud_oauth_client"] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _stdout(state: dict, before: str = "", after: str = "") -> str:
    return f"{before}NC_OAUTH_CLIENT {json.dumps(state)}\n{after}"


class TestNextcloudOauthClientState(unittest.TestCase):
    def test_an_unchanged_client_without_stale_clients_is_not_changed(self):
        state = MODULE.nextcloud_oauth_client_state(
            _stdout({"action": "unchanged", "id": 7, "client_id": "abc", "removed": 0})
        )
        self.assertFalse(state["changed"])
        self.assertEqual(state["id"], 7)

    def test_removing_a_stale_client_is_a_change(self):
        state = MODULE.nextcloud_oauth_client_state(
            _stdout({"action": "unchanged", "id": 7, "client_id": "abc", "removed": 2})
        )
        self.assertTrue(state["changed"])

    def test_a_fixed_redirect_and_a_created_client_are_changes(self):
        for action in ("redirect_fixed", "created"):
            with self.subTest(action=action):
                state = MODULE.nextcloud_oauth_client_state(
                    _stdout(
                        {"action": action, "id": 7, "client_id": "abc", "removed": 0}
                    )
                )
                self.assertTrue(state["changed"])

    def test_the_marker_is_found_among_php_notices(self):
        state = MODULE.nextcloud_oauth_client_state(
            _stdout(
                {
                    "action": "created",
                    "id": 9,
                    "client_id": "x",
                    "client_secret": "s",
                    "removed": 1,
                },
                before="PHP Deprecated: something\n",
                after="PHP Notice: else\n",
            )
        )
        self.assertEqual(state["action"], "created")
        self.assertEqual(state["client_secret"], "s")

    def test_a_missing_or_doubled_marker_fails(self):
        line = _stdout({"action": "unchanged", "id": 1, "client_id": "a", "removed": 0})
        for stdout in ("", "PHP Fatal error: class not found\n", line + line):
            with (
                self.subTest(stdout=stdout[:20]),
                self.assertRaises(AnsibleFilterError),
            ):
                MODULE.nextcloud_oauth_client_state(stdout)

    def test_an_unknown_action_fails(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.nextcloud_oauth_client_state(
                _stdout({"action": "deleted", "id": 1, "client_id": "a", "removed": 0})
            )


if __name__ == "__main__":
    unittest.main()
