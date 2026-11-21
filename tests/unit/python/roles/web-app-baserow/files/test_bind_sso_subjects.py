from __future__ import annotations

import importlib.util
import unittest

from utils.cache.files import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "roles/web-app-baserow/files/python/bind_sso_subjects.py"
ADMIN = ("administrator", "administrator@example.org")
ALICE = {
    "username": "alice",
    "email": "Alice@Example.org",
    "emailVerified": True,
    "id": "kc-alice",
}
ALICE_ACCOUNT = {"id": 7, "email": "alice@example.org"}


def _plan():
    spec = importlib.util.spec_from_file_location("bind_sso_subjects", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plan


class TestBindSsoSubjects(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()

    def test_an_unbound_account_with_a_verified_matching_email_is_bound(self):
        self.assertEqual(
            self.plan([ALICE], [ALICE_ACCOUNT], {}, *ADMIN), ([(7, "alice")], [])
        )

    def test_the_administrator_is_bound_to_the_bootstrap_account_by_username(self):
        directory = [{**ALICE, "username": ADMIN[0], "emailVerified": False}]
        self.assertEqual(
            self.plan(directory, [{"id": 1, "email": ADMIN[1]}], {}, *ADMIN),
            ([(1, ADMIN[0])], []),
        )

    def test_an_unverified_keycloak_email_is_skipped_by_username(self):
        bind, skipped = self.plan(
            [{**ALICE, "emailVerified": False}], [ALICE_ACCOUNT], {}, *ADMIN
        )
        self.assertEqual(bind, [])
        self.assertEqual(skipped, [("alice", "the Keycloak email is not verified")])
        self.assertNotIn("@", repr(skipped))

    def test_an_account_linked_to_another_username_is_never_rebound(self):
        self.assertEqual(
            self.plan([ALICE], [ALICE_ACCOUNT], {"alice-old": 7}, *ADMIN),
            ([], [("alice", "the account is linked to another identity")]),
        )

    def test_a_username_another_account_holds_is_never_moved(self):
        self.assertEqual(
            self.plan([ALICE], [ALICE_ACCOUNT], {"alice": 9}, *ADMIN),
            ([], [("alice", "the identity is linked to another account")]),
        )

    def test_an_account_already_bound_to_its_username_is_left_alone(self):
        self.assertEqual(
            self.plan([ALICE], [ALICE_ACCOUNT], {"alice": 7}, *ADMIN), ([], [])
        )


if __name__ == "__main__":
    unittest.main()
