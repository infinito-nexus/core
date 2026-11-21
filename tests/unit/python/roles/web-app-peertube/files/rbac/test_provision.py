import contextlib
import io
import json
import types
import unittest
import urllib.error
import urllib.parse

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-peertube"
    / "files"
    / "python"
    / "rbac"
    / "provision.py"
)
ROLE_IDS = {"administrator": 0, "moderator": 1, "user": 2}


def load_module():
    module = types.ModuleType("peertube_rbac_provision")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


def member(username, email):
    return {"username": username, "email": email, "name": ""}


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePeertube:
    """PeerTube's user API.

    Args:
        accounts: the accounts that exist before the run; one without
            ``pluginAuth`` is local.
        conflicts: username -> account that a 409 leaves behind, or None when the
            409 stems from a channel name or a deleted account's actor.
        errors: username -> HTTP status its creation answers.
        page_size: accounts per listing page.
    """

    def __init__(self, accounts=(), conflicts=None, errors=None, page_size=2):
        self.accounts = [{"pluginAuth": None, **account} for account in accounts]
        self.conflicts = dict(conflicts or {})
        self.errors = dict(errors or {})
        self.page_size = page_size
        self.requests = []

    def __call__(self, request, timeout):
        body = request.data.decode() if request.data else ""
        self.requests.append((request.full_url, dict(request.header_items()), body))
        url = urllib.parse.urlsplit(request.full_url)
        query = urllib.parse.parse_qs(url.query)
        if url.path.endswith("/oauth-clients/local"):
            return FakeResponse(
                json.dumps({"client_id": "cid", "client_secret": "cs"}).encode()
            )
        if url.path.endswith("/users/token"):
            return FakeResponse(json.dumps({"access_token": "tok"}).encode())
        if request.data is None and "search" in query:
            needle = query["search"][0].lower()
            found = [a for a in self.accounts if needle in a["email"].lower()]
            return FakeResponse(
                json.dumps({"total": len(found), "data": found}).encode()
            )
        if request.data is None:
            start = int(query["start"][0])
            page = self.accounts[start : start + self.page_size]
            return FakeResponse(
                json.dumps({"total": len(self.accounts), "data": page}).encode()
            )
        created = json.loads(body)
        if created["username"] in self.errors:
            status = self.errors[created["username"]]
            raise urllib.error.HTTPError(
                request.full_url, status, "Error", {}, io.BytesIO(b'{"detail":"boom"}')
            )
        if created["username"] in self.conflicts:
            left = self.conflicts[created["username"]]
            if left is not None:
                self.accounts.append({"pluginAuth": None, **left})
            raise urllib.error.HTTPError(
                request.full_url, 409, "Conflict", {}, io.BytesIO(b'{"detail":"taken"}')
            )
        self.accounts.append(
            {
                "username": created["username"],
                "email": created["email"],
                "pluginAuth": None,
            }
        )
        return FakeResponse(json.dumps({"user": {"id": 7}}).encode())


class PeertubeRbacProvisionTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def payload(self, members):
        return {
            "url": "http://127.0.0.1:9000",
            "hostname": "video.example.org",
            "root_username": "root",
            "root_password": "root-secret",
            "role_ids": ROLE_IDS,
            "members": members,
        }

    def run_main(self, members, peertube):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.mod.main(self.payload(members), peertube)
        return code, json.loads(stdout.getvalue())

    def creations(self, peertube):
        return [
            json.loads(body)
            for url, _, body in peertube.requests
            if url.endswith("/api/v1/users") and body
        ]

    def test_only_members_without_an_account_are_created(self):
        peertube = FakePeertube(
            accounts=[
                {"username": "root", "email": "root@example.org"},
                {"username": "alice", "email": "Alice@Example.org"},
                {"username": "dave", "email": "dave@example.org"},
            ]
        )
        members = {
            "administrator": [
                member("alice", "alice@example.org"),
                member("noemail", ""),
            ],
            "moderator": [
                member("alice", "alice@example.org"),
                member("bob", "bob@example.org"),
            ],
        }

        code, result = self.run_main(members, peertube)

        self.assertEqual(
            (0, {"created": ["bob@example.org"], "failed": []}), (code, result)
        )
        created = self.creations(peertube)
        self.assertEqual([("bob", 1)], [(c["username"], c["role"]) for c in created])
        self.assertEqual(48, len(created[0]["password"]))

    def test_a_self_registration_with_a_members_email_is_a_warning(self):
        """mallory registered with carol's e-mail before carol had an account; a
        stranger's signup must not fail every deploy."""
        peertube = FakePeertube(
            accounts=[{"username": "mallory", "email": "Carol@example.org"}]
        )

        code, result = self.run_main(
            {"administrator": [member("carol", "carol@example.org")], "moderator": []},
            peertube,
        )

        self.assertEqual(0, code)
        self.assertEqual([], self.creations(peertube))
        self.assertEqual(
            [
                {
                    "username": "carol",
                    "status": None,
                    "body": "e-mail of carol is held by account mallory",
                    "warning": True,
                }
            ],
            result["failed"],
        )

    def test_a_local_username_held_with_another_email_is_a_warning(self):
        peertube = FakePeertube(
            accounts=[{"username": "carol", "email": "mallory@example.org"}]
        )

        code, result = self.run_main(
            {"administrator": [member("carol", "carol@example.org")], "moderator": []},
            peertube,
        )

        self.assertEqual(0, code)
        self.assertEqual([], self.creations(peertube))
        self.assertIn(
            "username carol is held by an account with another e-mail",
            result["failed"][0]["body"],
        )
        self.assertIs(True, result["failed"][0]["warning"])

    def test_an_oidc_account_with_a_changed_email_is_no_conflict(self):
        """PeerTube keeps the e-mail it first saw, so the directory may differ."""
        plugin = "peertube-plugin-auth-openid-connect"
        peertube = FakePeertube(
            accounts=[
                {"username": "carol", "email": "old@example.org", "pluginAuth": plugin},
                {"username": "dan", "email": "dan@example.org", "pluginAuth": plugin},
            ]
        )

        code, result = self.run_main(
            {
                "administrator": [member("carol", "carol@example.org")],
                "moderator": [member("daniel", "dan@example.org")],
            },
            peertube,
        )

        self.assertEqual((0, {"created": [], "failed": []}), (code, result))
        self.assertEqual([], self.creations(peertube))

    def test_a_create_error_fails_even_beside_a_warning(self):
        peertube = FakePeertube(
            accounts=[{"username": "mallory", "email": "carol@example.org"}],
            errors={"bob": 500},
        )

        code, result = self.run_main(
            {
                "administrator": [member("carol", "carol@example.org")],
                "moderator": [member("bob", "bob@example.org")],
            },
            peertube,
        )

        self.assertEqual(1, code)
        self.assertEqual(
            [("carol", True), ("bob", False)],
            [(f["username"], f["warning"]) for f in result["failed"]],
        )

    def test_a_2xx_that_is_no_json_is_a_named_failure_of_that_member(self):
        class NotJson(FakePeertube):
            def __call__(self, request, timeout):
                if (
                    request.data
                    and request.full_url.endswith("/api/v1/users")
                    and b"alice" in request.data
                ):
                    return FakeResponse(b"<html>proxy</html>")
                return super().__call__(request, timeout)

        members = {
            "administrator": [member("alice", "alice@example.org")],
            "moderator": [member("bob", "bob@example.org")],
        }

        code, result = self.run_main(members, NotJson())

        self.assertEqual(1, code)
        self.assertEqual(["bob@example.org"], result["created"])
        self.assertEqual(
            ["alice"], [failure["username"] for failure in result["failed"]]
        )

    def test_a_409_leaving_an_account_with_another_username_is_a_failure(self):
        code, result = self.run_main(
            {"administrator": [member("alice", "alice@example.org")], "moderator": []},
            FakePeertube(
                conflicts={
                    "alice": {"username": "mallory", "email": "alice@example.org"}
                }
            ),
        )

        self.assertEqual(1, code)
        self.assertEqual(409, result["failed"][0]["status"])

    def test_every_page_of_the_account_list_is_read(self):
        peertube = FakePeertube(
            accounts=[
                {"username": f"u{i}", "email": f"u{i}@example.org"} for i in range(5)
            ],
            page_size=2,
        )

        code, result = self.run_main(
            {"administrator": [member("u4", "u4@example.org")], "moderator": []},
            peertube,
        )

        self.assertEqual((0, {"created": [], "failed": []}), (code, result))
        listed = [
            url for url, _, body in peertube.requests if "/api/v1/users?start" in url
        ]
        self.assertEqual(3, len(listed))

    def test_requests_go_to_the_namespace_url_as_root_with_the_host_header(self):
        peertube = FakePeertube()

        self.run_main(
            {"administrator": [member("alice", "alice@example.org")], "moderator": []},
            peertube,
        )

        token_form = urllib.parse.parse_qs(peertube.requests[1][2])
        self.assertEqual(["root"], token_form["username"])
        self.assertEqual(["root-secret"], token_form["password"])
        self.assertTrue(
            all(
                url.startswith("http://127.0.0.1:9000/api/v1/")
                for url, _, _ in peertube.requests
            )
        )
        creation = next(
            headers
            for url, headers, body in peertube.requests
            if body and url.endswith("/users")
        )
        self.assertEqual("Bearer tok", creation["Authorization"])
        self.assertEqual("video.example.org", creation["Host"])

    def test_no_member_touches_no_api(self):
        peertube = FakePeertube()

        self.assertEqual(
            (0, {"created": [], "failed": []}),
            self.run_main({"administrator": [], "moderator": []}, peertube),
        )
        self.assertEqual([], peertube.requests)

    def test_a_409_counts_when_the_account_exists_afterwards(self):
        code, result = self.run_main(
            {"administrator": [member("alice", "alice@example.org")], "moderator": []},
            FakePeertube(
                conflicts={"alice": {"username": "alice", "email": "alice@example.org"}}
            ),
        )

        self.assertEqual(
            (0, {"created": ["alice@example.org"], "failed": []}), (code, result)
        )

    def test_a_409_without_the_account_is_a_named_failure(self):
        """A taken channel name or a deleted account's actor also answers 409."""
        code, result = self.run_main(
            {"administrator": [member("alice", "alice@example.org")], "moderator": []},
            FakePeertube(conflicts={"alice": None}),
        )

        self.assertEqual(1, code)
        self.assertEqual([], result["created"])
        self.assertEqual(
            [
                {
                    "username": "alice",
                    "status": 409,
                    "body": '{"detail":"taken"}',
                    "warning": False,
                }
            ],
            result["failed"],
        )

    def test_a_failing_member_is_named_and_the_others_are_still_created(self):
        members = {
            "administrator": [member("alice", "alice@example.org")],
            "moderator": [member("bob", "bob@example.org")],
        }

        code, result = self.run_main(members, FakePeertube(errors={"alice": 500}))

        self.assertEqual(1, code)
        self.assertEqual(["bob@example.org"], result["created"])
        self.assertEqual(
            [
                {
                    "username": "alice",
                    "status": 500,
                    "body": '{"detail":"boom"}',
                    "warning": False,
                }
            ],
            result["failed"],
        )


if __name__ == "__main__":
    unittest.main()
