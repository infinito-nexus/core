import contextlib
import io
import json
import os
import sys
import unittest
import unittest.mock as mock
import urllib.parse

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))

import email_verified as m


class FakeKeycloak:
    def __init__(self):
        self.users = {}
        self.puts = []
        self.failing = set()

    def add_user(self, username, verified, **extra):
        user_id = f"u-{len(self.users) + 1}"
        self.users[user_id] = {
            "id": user_id,
            "username": username,
            "emailVerified": verified,
            **extra,
        }
        return user_id

    def call(self, method, path, payload=None, timeout=60):
        route, _, query = path.partition("?")
        if method == "GET" and route == "users":
            wanted = urllib.parse.parse_qs(query)["username"][0]
            if wanted in self.failing:
                raise m.KeycloakError(f"GET {path}: HTTP 500")
            return [
                dict(u) for u in self.users.values() if wanted.lower() in u["username"]
            ], ""
        if method == "GET" and route.startswith("users/"):
            return dict(self.users[route.split("/")[1]]), ""
        if method == "PUT" and route.startswith("users/"):
            user_id = route.split("/")[1]
            self.puts.append(user_id)
            self.users[user_id] = dict(payload)
            return None, ""
        raise AssertionError(f"unexpected call {method} {path}")


class TestVerify(unittest.TestCase):
    def test_an_unverified_user_holding_its_inventory_address_is_updated(self):
        kc = FakeKeycloak()
        user_id = kc.add_user("biber", False, email="biber@example.org", firstName="B")
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "updated")
        self.assertIs(kc.users[user_id]["emailVerified"], True)
        self.assertEqual(kc.users[user_id]["email"], "biber@example.org")
        self.assertEqual(kc.users[user_id]["firstName"], "B")

    def test_a_user_holding_another_address_is_never_marked_verified(self):
        kc = FakeKeycloak()
        user_id = kc.add_user("biber", False, email="erpnext-api-bot@example.org")
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "mismatch")
        self.assertIs(kc.users[user_id]["emailVerified"], False)
        self.assertEqual(kc.puts, [])

    def test_a_user_without_an_address_is_never_marked_verified(self):
        kc = FakeKeycloak()
        kc.add_user("biber", False)
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "mismatch")
        self.assertEqual(kc.puts, [])

    def test_the_addresses_compare_case_insensitively(self):
        kc = FakeKeycloak()
        kc.add_user("biber", False, email="biber@example.org")
        self.assertEqual(m.verify(kc, "biber", "Biber@Example.org"), "updated")

    def test_a_verified_user_holding_its_inventory_address_is_left_alone(self):
        kc = FakeKeycloak()
        kc.add_user("biber", True, email="biber@example.org")
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "unchanged")
        self.assertEqual(kc.puts, [])

    def test_an_absent_user_is_reported_missing(self):
        kc = FakeKeycloak()
        self.assertEqual(m.verify(kc, "biber", "biber@example.org"), "missing")
        self.assertEqual(kc.puts, [])

    def test_only_the_exact_username_is_touched(self):
        kc = FakeKeycloak()
        other = kc.add_user("contact2", False, email="contact@example.org")
        target = kc.add_user("contact", False, email="contact@example.org")
        self.assertEqual(m.verify(kc, "Contact", "contact@example.org"), "updated")
        self.assertEqual(kc.puts, [target])
        self.assertIs(kc.users[other]["emailVerified"], False)


class TestMain(unittest.TestCase):
    def _run(self, kc, emails):
        out = io.StringIO()
        env = {
            "KC_URL": "http://kc",
            "KC_PID": "1",
            "KC_REALM": "r",
            "EMAILS_JSON": json.dumps(emails),
        }
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(m, "Keycloak", lambda *args: kc),
            mock.patch.object(m, "container_credentials", lambda path: ("a", "p")),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = m.main()
        return code, out.getvalue().splitlines()

    def test_the_summary_counts_every_outcome(self):
        kc = FakeKeycloak()
        kc.add_user("administrator", True, email="administrator@example.org")
        kc.add_user("biber", False, email="biber@example.org")
        kc.add_user("mallory", False, email="erpnext-api-bot@example.org")
        code, lines = self._run(
            kc,
            {
                "administrator": "administrator@example.org",
                "biber": "biber@example.org",
                "mallory": "mallory@example.org",
                "ghost": "ghost@example.org",
            },
        )
        self.assertEqual(code, 0)
        self.assertIn("mismatch mallory", lines)
        self.assertEqual(
            lines[-1],
            "summary updated=1 unchanged=1 mismatch=1 missing=1 failed=0",
        )

    def test_one_failed_user_fails_the_run_but_not_the_others(self):
        kc = FakeKeycloak()
        kc.add_user("administrator", False, email="administrator@example.org")
        kc.add_user("biber", False, email="biber@example.org")
        kc.failing.add("administrator")
        code, lines = self._run(
            kc,
            {
                "administrator": "administrator@example.org",
                "biber": "biber@example.org",
            },
        )
        self.assertEqual(code, 1)
        self.assertIn("failed administrator", lines)
        self.assertIn("updated biber", lines)

    def test_a_missing_environment_key_fails_before_any_call(self):
        kc = FakeKeycloak()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(m, "Keycloak", lambda *args: kc),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            code = m.main()
        self.assertEqual(code, 1)
        self.assertTrue(out.getvalue().startswith("setup-failed"))

    def test_emails_that_are_no_username_to_address_object_fail_before_any_call(
        self,
    ):
        kc = FakeKeycloak()
        kc.add_user("biber", False, email="biber@example.org")
        out = io.StringIO()
        env = {
            "KC_URL": "http://kc",
            "KC_PID": "1",
            "KC_REALM": "r",
            "EMAILS_JSON": json.dumps(["biber"]),
        }
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(m, "Keycloak", lambda *args: kc),
            mock.patch.object(m, "container_credentials", lambda path: ("a", "p")),
            contextlib.redirect_stdout(out),
        ):
            code = m.main()
        self.assertEqual(code, 1)
        self.assertTrue(out.getvalue().startswith("setup-failed"))
        self.assertEqual(kc.puts, [])


if __name__ == "__main__":
    unittest.main()
