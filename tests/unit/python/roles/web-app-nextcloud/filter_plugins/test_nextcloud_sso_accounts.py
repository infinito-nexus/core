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


MODULE = _load_module()
REKEYED = MODULE.nextcloud_rekeyed_accounts
SUBJECTS = MODULE.nextcloud_sociallogin_subjects
PROVIDER = "web-app-keycloak"
SUB = "3f2a9c4e-0b1d-4e5f-8a6b-7c8d9e0f1a2b"
SUB2 = "8d1e2f3a-4b5c-4d6e-9f0a-1b2c3d4e5f60"
CREATED = f"{PROVIDER}-{SUB}"
CONNECTED = {"uid": "carol", "identifier": f"{PROVIDER}-{SUB}"}
PLUGINS = ("sociallogin", "user_oidc", "oidc_login")


def _probe(
    created=(),
    connected=(),
    user_oidc=(),
    ldap=(),
    before: str = "",
    after: str = "",
    providers=(PROVIDER,),
) -> dict:
    state = {
        "sociallogin": {
            "providers": list(providers),
            "created": list(created),
            "connected": list(connected),
        },
        "user_oidc": list(user_oidc),
        "ldap": list(ldap),
    }
    return {"stdout": f"{before}SSO_ACCOUNTS {json.dumps(state)}\n{after}"}


def _result(sub: str, uid: str, outcome: str, held=()) -> dict:
    return {"id": sub, "value": uid, "outcome": outcome, "held": list(held)}


class TestNextcloudRekeyedAccounts(unittest.TestCase):
    def test_an_instance_without_accounts_keeps_every_switch(self):
        for target in PLUGINS:
            for ldap in (True, False):
                with self.subTest(target=target, ldap=ldap):
                    self.assertEqual(REKEYED(_probe(), target, ldap, []), [])

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
                self.assertEqual(REKEYED(probe, target, ldap, []), sorted(rekeyed))

    def test_the_oidc_login_flip_on_ldap_enable_refuses_sociallogin_accounts(self):
        self.assertEqual(
            REKEYED(_probe(created=[CREATED], ldap=["alice"]), "oidc_login", True, []),
            [f"{CREATED} (created by sociallogin)"],
        )

    def test_a_marked_account_outside_the_provider_keeps_its_user_id(self):
        probe = _probe(
            created=["alice", f"retired-{SUB}"],
            connected=[{"uid": "dave", "identifier": f"retired-{SUB}"}],
        )
        for target in ("user_oidc", "oidc_login"):
            with self.subTest(target=target):
                self.assertEqual(REKEYED(probe, target, True, []), [])

    def test_boot_output_around_the_state_line_is_ignored(self):
        self.assertEqual(
            REKEYED(
                _probe(before="PHP Deprecated: legacy call\n", after="\n"),
                "user_oidc",
                True,
                [],
            ),
            [],
        )

    def test_a_probe_without_exactly_one_state_line_fails_closed(self):
        for stdout in (
            "",
            "PHP Fatal error: database unreachable\n",
            _probe()["stdout"] * 2,
        ):
            for check in (
                lambda probe: REKEYED(probe, "user_oidc", True, []),
                SUBJECTS,
            ):
                with self.subTest(stdout=stdout), self.assertRaises(ValueError):
                    check({"stdout": stdout})

    def test_an_unknown_target_fails_closed(self):
        for target in ("", "openid", "User_OIDC"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                REKEYED(_probe(), target, True, [])

    def test_each_sociallogin_account_is_paired_with_its_keycloak_user(self):
        probe = _probe(
            created=[CREATED, "alice", f"retired-{SUB}"],
            connected=[
                {"uid": "carol", "identifier": f"{PROVIDER}-{SUB2}"},
                {"uid": "dave", "identifier": f"retired-{SUB2}"},
            ],
        )
        self.assertEqual(
            SUBJECTS(probe),
            [{"id": SUB, "value": CREATED}, {"id": SUB2, "value": "carol"}],
        )

    def test_the_longest_provider_prefix_names_the_keycloak_user(self):
        probe = _probe(
            created=[f"{PROVIDER}-old-{SUB}"], providers=(PROVIDER, f"{PROVIDER}-old")
        )
        self.assertEqual(
            SUBJECTS(probe), [{"id": SUB, "value": f"{PROVIDER}-old-{SUB}"}]
        )

    def test_a_switch_to_user_oidc_keeps_the_accounts_keycloak_took_the_user_id_of(
        self,
    ):
        probe = _probe(created=[CREATED], connected=[CONNECTED])
        results = [
            _result(SUB, CREATED, "updated"),
            _result(SUB, "carol", "unchanged", held=["carol"]),
        ]
        self.assertEqual(REKEYED(probe, "user_oidc", True, results), [])

    def test_every_account_keycloak_did_not_take_the_user_id_of_is_named(self):
        probe = _probe(created=[CREATED])
        for outcome, held, reason in (
            ("conflict", ["alice"], "holds the user id alice already"),
            ("taken", [], "would share it with the user whose username it is"),
            ("missing", [], "is absent from the realm"),
            ("dropped", [], "kept no user id"),
            ("failed", [], "could not be given the user id"),
        ):
            with self.subTest(outcome=outcome):
                self.assertEqual(
                    REKEYED(
                        probe,
                        "user_oidc",
                        True,
                        [_result(SUB, CREATED, outcome, held)],
                    ),
                    [
                        f"{CREATED} (created by sociallogin, Keycloak user {SUB} {reason})"
                    ],
                )

    def test_a_written_user_id_maps_only_its_own_account_and_only_for_user_oidc(self):
        probe = _probe(created=[CREATED])
        label = f"{CREATED} (created by sociallogin)"
        for target, results in (
            ("user_oidc", [_result(SUB2, CREATED, "updated")]),
            ("user_oidc", [_result(SUB, "carol", "updated")]),
            ("oidc_login", [_result(SUB, CREATED, "updated")]),
        ):
            with self.subTest(target=target, results=results):
                self.assertEqual(REKEYED(probe, target, True, results), [label])


if __name__ == "__main__":
    unittest.main()
