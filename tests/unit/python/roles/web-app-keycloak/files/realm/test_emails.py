import contextlib
import io
import json
import sys
import unittest
import unittest.mock as mock
import urllib.parse

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))

from realm import emails as m


class FakeKeycloak:
    def __init__(self, users):
        self.users = users
        self.calls = []

    def call(self, method, path, payload=None, timeout=60):
        self.calls.append((method, path))
        route, _, query = path.partition("?")
        if method == "GET" and route == "users":
            params = urllib.parse.parse_qs(query)
            first = int(params["first"][0])
            size = int(params["max"][0])
            return self.users[first : first + size], 200
        if method == "POST" and route.startswith("user-storage/"):
            return {}, 204
        raise AssertionError(f"unexpected call {method} {path}")


class TestEmails(unittest.TestCase):
    def test_every_page_is_read_and_users_without_email_are_left_out(self):
        users = [
            {"username": f"user{i}", "email": f"user{i}@example.org"}
            for i in range(m.PAGE + 3)
        ]
        users.append({"username": "noemail"})
        kc = FakeKeycloak(users)

        found = m.emails(kc)

        self.assertEqual(m.PAGE + 3, len(found))
        self.assertNotIn("noemail", found)
        self.assertEqual("user0@example.org", found["user0"])
        self.assertEqual(2, sum(1 for method, _ in kc.calls if method == "GET"))


class TestMain(unittest.TestCase):
    def run_main(self, kc, component):
        env = {
            "KC_URL": "http://keycloak:8080",
            "KC_PID": "1",
            "KC_REALM": "infinito",
            "LDAP_COMPONENT_ID": component,
        }
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(m.os.environ, env, clear=True),
            mock.patch.object(m, "Keycloak", return_value=kc),
            mock.patch.object(m, "container_credentials", return_value=("a", "b")),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = m.main()
        return code, out.getvalue(), err.getvalue()

    def test_a_full_ldap_sync_runs_before_the_read(self):
        kc = FakeKeycloak([{"username": "biber", "email": "biber@example.org"}])

        code, out, _ = self.run_main(kc, "ldap-1")

        self.assertEqual(0, code)
        self.assertEqual({"biber": "biber@example.org"}, json.loads(out))
        self.assertEqual("POST", kc.calls[0][0])
        self.assertIn("ldap-1/sync?action=triggerFullSync", kc.calls[0][1])

    def test_no_sync_without_a_component(self):
        kc = FakeKeycloak([])

        code, out, _ = self.run_main(kc, "")

        self.assertEqual(0, code)
        self.assertEqual({}, json.loads(out))
        self.assertTrue(all(method == "GET" for method, _ in kc.calls))

    def test_a_keycloak_error_fails_without_printing_a_partial_object(self):
        kc = FakeKeycloak([])
        kc.call = mock.Mock(side_effect=m.KeycloakError("GET users: HTTP 500"))

        code, out, err = self.run_main(kc, "")

        self.assertEqual(1, code)
        self.assertEqual("", out)
        self.assertIn("read-failed", err)


if __name__ == "__main__":
    unittest.main()
