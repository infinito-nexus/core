from __future__ import annotations

import importlib.util
import json
import sys
import unittest

from . import PROJECT_ROOT


def _load_module():
    path = (
        PROJECT_ROOT / "roles/web-app-nextcloud/filter_plugins/nextcloud_sociallogin.py"
    )
    spec = importlib.util.spec_from_file_location("nextcloud_sociallogin", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["nextcloud_sociallogin"] = module
    spec.loader.exec_module(module)
    return module


ACCOUNTS = _load_module().nextcloud_sociallogin_accounts
SUB = "3f2a9c4e-0b1d-4e5f-8a6b-7c8d9e0f1a2b"


def _probe(created=(), connected=(), before: str = "", after: str = "") -> dict:
    state = {"created": list(created), "connected": list(connected)}
    return {"stdout": f"{before}SOCIALLOGIN_ACCOUNTS {json.dumps(state)}\n{after}"}


class TestNextcloudSocialloginAccounts(unittest.TestCase):
    def test_an_instance_without_sociallogin_accounts_names_none(self):
        self.assertEqual(ACCOUNTS(_probe()), [])

    def test_a_created_account_is_named(self):
        self.assertEqual(
            ACCOUNTS(_probe(created=[f"keycloak-{SUB}"])),
            [f"keycloak-{SUB} (created by sociallogin)"],
        )

    def test_a_connected_login_is_named_with_the_identity_it_belongs_to(self):
        self.assertEqual(
            ACCOUNTS(
                _probe(
                    connected=[
                        {"uid": "administrator", "identifier": f"keycloak-{SUB}"}
                    ]
                )
            ),
            [f"administrator (connected to keycloak-{SUB})"],
        )

    def test_every_account_is_named_once_per_kind_in_a_stable_order(self):
        self.assertEqual(
            ACCOUNTS(
                _probe(
                    created=["keycloak-b", "keycloak-a"],
                    connected=[{"uid": "alice", "identifier": "keycloak-c"}],
                )
            ),
            [
                "alice (connected to keycloak-c)",
                "keycloak-a (created by sociallogin)",
                "keycloak-b (created by sociallogin)",
            ],
        )

    def test_boot_output_around_the_state_line_is_ignored(self):
        self.assertEqual(
            ACCOUNTS(_probe(before="PHP Deprecated: legacy call\n", after="\n")), []
        )

    def test_a_probe_without_exactly_one_state_line_fails_closed(self):
        for stdout in (
            "",
            "PHP Fatal error: database unreachable\n",
            'SOCIALLOGIN_ACCOUNTS {"created": [], "connected": []}\n' * 2,
        ):
            with self.subTest(stdout=stdout), self.assertRaises(ValueError):
                ACCOUNTS({"stdout": stdout})


if __name__ == "__main__":
    unittest.main()
