import contextlib
import io
import json
import types
import unittest
import urllib.error

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles" / "web-app-matrix" / "files" / "python" / "rbac_sync.py"
SERVER = "example.org"


def load_module():
    module = types.ModuleType("matrix_rbac_sync")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return json.dumps(self.body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSynapse:
    def __init__(self, users, next_token=False, refuse_logins=0):
        self.users = users
        self.next_token = next_token
        self.refuse_logins = refuse_logins
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request.get_method(), request.full_url, request.data))
        if request.full_url.endswith("/login"):
            if self.refuse_logins:
                self.refuse_logins -= 1
                raise urllib.error.URLError("connection refused")
            return FakeResponse({"access_token": "tok"})
        if "/_synapse/admin/v2/users?" in request.full_url:
            listing = {"users": self.users}
            if self.next_token:
                listing["next_token"] = "100"
            return FakeResponse(listing)
        return FakeResponse({})

    def puts(self):
        return [
            (url, json.loads(data))
            for method, url, data in self.requests
            if method == "PUT"
        ]

    def logged_out(self):
        return any(url.endswith("/logout") for _, url, _ in self.requests)


def environ(members):
    return {
        "MATRIX_SYNAPSE_URL": "http://127.0.0.1:8008",
        "MATRIX_SERVER_NAME": SERVER,
        "MATRIX_ADMIN_USERNAME": "platformadmin",
        "MATRIX_ADMIN_PASSWORD": "secret",
        "MATRIX_RBAC_PROTECTED_MXIDS": json.dumps(
            [f"@platformadmin:{SERVER}", f"@chatgptbot:{SERVER}"]
        ),
        "MATRIX_RBAC_PAGE_SIZE": "100000",
        "RBAC_ADMINISTRATORS": json.dumps(members),
    }


def user(localpart, admin):
    return {"name": f"@{localpart}:{SERVER}", "admin": admin}


class MatrixRbacSyncTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def run_main(self, synapse, members):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(environ(members), opener=synapse, sleep=lambda seconds: None)
        return stdout.getvalue().splitlines()

    def test_members_are_granted_and_outsiders_revoked_but_protected_ids_kept(self):
        synapse = FakeSynapse(
            [
                user("alice", False),
                user("mallory", True),
                user("platformadmin", True),
                user("chatgptbot", True),
            ]
        )

        output = self.run_main(synapse, ["Alice"])

        self.assertEqual(
            synapse.puts(),
            [
                (
                    f"http://127.0.0.1:8008/_synapse/admin/v2/users/%40alice%3A{SERVER}",
                    {"admin": True},
                ),
                (
                    f"http://127.0.0.1:8008/_synapse/admin/v2/users/%40mallory%3A{SERVER}",
                    {"admin": False},
                ),
            ],
        )
        self.assertEqual(
            output,
            [
                f"CHANGED @alice:{SERVER} admin=true",
                f"CHANGED @mallory:{SERVER} admin=false",
            ],
        )
        self.assertTrue(synapse.logged_out())

    def test_a_converged_server_reports_unchanged(self):
        synapse = FakeSynapse([user("alice", True), user("bob", False)])

        self.assertEqual(self.run_main(synapse, ["alice"]), ["UNCHANGED"])
        self.assertEqual(synapse.puts(), [])

    def test_more_than_one_page_stops_the_run_and_still_logs_out(self):
        synapse = FakeSynapse([user("alice", False)], next_token=True)

        with self.assertRaises(SystemExit):
            self.run_main(synapse, ["alice"])
        self.assertEqual(synapse.puts(), [])
        self.assertTrue(synapse.logged_out())

    def test_the_login_is_retried_while_synapse_starts(self):
        synapse = FakeSynapse([user("alice", False)], refuse_logins=2)

        self.assertEqual(
            self.run_main(synapse, ["alice"]), [f"CHANGED @alice:{SERVER} admin=true"]
        )


if __name__ == "__main__":
    unittest.main()
