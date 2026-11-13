from __future__ import annotations

import importlib.util
import json
import sys
import unittest

from . import PROJECT_ROOT


def _load_module():
    path = (
        PROJECT_ROOT
        / "roles/web-app-nextcloud/filter_plugins/nextcloud_sso_accounts.py"
    )
    spec = importlib.util.spec_from_file_location("nextcloud_sso_accounts", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["nextcloud_sso_accounts"] = module
    spec.loader.exec_module(module)
    return module


REKEYED = _load_module().nextcloud_rekeyed_accounts
PROVIDER = "web-app-keycloak"
SUB = "3f2a9c4e-0b1d-4e5f-8a6b-7c8d9e0f1a2b"
CREATED = f"{PROVIDER}-{SUB}"
CONNECTED = {"uid": "carol", "identifier": f"{PROVIDER}-{SUB}"}
PLUGINS = ("sociallogin", "user_oidc", "oidc_login")


def _probe(
    created=(), connected=(), user_oidc=(), ldap=(), before: str = "", after: str = ""
) -> dict:
    state = {
        "sociallogin": {
            "providers": [PROVIDER],
            "created": list(created),
            "connected": list(connected),
        },
        "user_oidc": list(user_oidc),
        "ldap": list(ldap),
    }
    return {"stdout": f"{before}SSO_ACCOUNTS {json.dumps(state)}\n{after}"}


class TestNextcloudRekeyedAccounts(unittest.TestCase):
    def test_an_instance_without_accounts_keeps_every_switch(self):
        for target in PLUGINS:
            for ldap in (True, False):
                with self.subTest(target=target, ldap=ldap):
                    self.assertEqual(REKEYED(_probe(), target, ldap), [])

    def test_every_switch_names_exactly_the_accounts_it_gives_a_new_user_id(self):
        probe = _probe(
            created=[CREATED], connected=[CONNECTED], user_oidc=["bob"], ldap=["alice"]
        )
        sociallogin = [
            f"carol (connected to {PROVIDER}-{SUB})",
            f"{CREATED} (created by sociallogin)",
        ]
        for target, ldap, rekeyed in (
            ("user_oidc", True, sociallogin),
            ("user_oidc", False, ["alice (LDAP account)", *sociallogin]),
            ("oidc_login", True, ["bob (user_oidc account)", *sociallogin]),
            (
                "oidc_login",
                False,
                ["alice (LDAP account)", "bob (user_oidc account)", *sociallogin],
            ),
            ("sociallogin", True, ["alice (LDAP account)", "bob (user_oidc account)"]),
            ("sociallogin", False, ["alice (LDAP account)", "bob (user_oidc account)"]),
        ):
            with self.subTest(target=target, ldap=ldap):
                self.assertEqual(REKEYED(probe, target, ldap), sorted(rekeyed))

    def test_the_oidc_login_flip_on_ldap_enable_refuses_sociallogin_accounts(self):
        self.assertEqual(
            REKEYED(_probe(created=[CREATED], ldap=["alice"]), "oidc_login", True),
            [f"{CREATED} (created by sociallogin)"],
        )

    def test_a_marked_account_outside_the_provider_keeps_its_user_id(self):
        probe = _probe(
            created=["alice", f"retired-{SUB}"],
            connected=[{"uid": "dave", "identifier": f"retired-{SUB}"}],
        )
        for target in ("user_oidc", "oidc_login"):
            with self.subTest(target=target):
                self.assertEqual(REKEYED(probe, target, True), [])

    def test_boot_output_around_the_state_line_is_ignored(self):
        self.assertEqual(
            REKEYED(
                _probe(before="PHP Deprecated: legacy call\n", after="\n"),
                "user_oidc",
                True,
            ),
            [],
        )

    def test_a_probe_without_exactly_one_state_line_fails_closed(self):
        for stdout in (
            "",
            "PHP Fatal error: database unreachable\n",
            _probe()["stdout"] * 2,
        ):
            with self.subTest(stdout=stdout), self.assertRaises(ValueError):
                REKEYED({"stdout": stdout}, "user_oidc", True)

    def test_an_unknown_target_fails_closed(self):
        for target in ("", "openid", "User_OIDC"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                REKEYED(_probe(), target, True)


if __name__ == "__main__":
    unittest.main()
