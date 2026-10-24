import contextlib
import io
import os
import sys
import unittest
import urllib.parse
from unittest import mock

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
    def test_an_unverified_user_is_updated_and_keeps_its_other_fields(self):
        kc = FakeKeycloak()
        user_id = kc.add_user("biber", False, email="biber@example.org")
        self.assertEqual(m.verify(kc, "biber"), "updated")
        self.assertIs(kc.users[user_id]["emailVerified"], True)
        self.assertEqual(kc.users[user_id]["email"], "biber@example.org")

    def test_a_verified_user_is_left_alone(self):
        kc = FakeKeycloak()
        kc.add_user("biber", True)
        self.assertEqual(m.verify(kc, "biber"), "unchanged")
        self.assertEqual(kc.puts, [])

    def test_an_absent_user_is_reported_missing(self):
        kc = FakeKeycloak()
        self.assertEqual(m.verify(kc, "biber"), "missing")
        self.assertEqual(kc.puts, [])

    def test_only_the_exact_username_is_touched(self):
        kc = FakeKeycloak()
        other = kc.add_user("contact2", False)
        target = kc.add_user("contact", False)
        self.assertEqual(m.verify(kc, "Contact"), "updated")
        self.assertEqual(kc.puts, [target])
        self.assertIs(kc.users[other]["emailVerified"], False)


class TestMain(unittest.TestCase):
    def _run(self, kc, usernames):
        out = io.StringIO()
        env = {
            "KC_URL": "http://kc",
            "KC_PID": "1",
            "KC_REALM": "r",
            "USERNAMES": usernames,
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
        kc.add_user("administrator", True)
        kc.add_user("biber", False)
        code, lines = self._run(kc, "administrator biber ghost")
        self.assertEqual(code, 0)
        self.assertEqual(lines[-1], "summary updated=1 unchanged=1 missing=1 failed=0")

    def test_one_failed_user_fails_the_run_but_not_the_others(self):
        kc = FakeKeycloak()
        kc.add_user("administrator", False)
        kc.add_user("biber", False)
        kc.failing.add("administrator")
        code, lines = self._run(kc, "administrator biber")
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


if __name__ == "__main__":
    unittest.main()
