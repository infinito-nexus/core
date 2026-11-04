import contextlib
import io
import json
import types
import unittest
from urllib.parse import parse_qs, urlsplit

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-litellm"
    / "files"
    / "python"
    / "rbac_reconcile.py"
)


def load_module():
    module = types.ModuleType("litellm_rbac_reconcile")
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


class FakeGateway:
    def __init__(self, users, page_size=2):
        self.users = users
        self.page_size = page_size
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        url = urlsplit(request.full_url)
        if url.path == "/user/list":
            page = int(parse_qs(url.query)["page"][0])
            start = (page - 1) * self.page_size
            total_pages = max(1, -(-len(self.users) // self.page_size))
            return FakeResponse(
                {
                    "users": self.users[start : start + self.page_size],
                    "total_pages": total_pages,
                }
            )
        return FakeResponse({"ok": True})

    def updates(self):
        return [json.loads(request.data) for request in self.requests if request.data]


def account(user_id, role, email=""):
    return {"user_id": user_id, "user_role": role, "user_email": email}


def member(username, email=""):
    return {"username": username, "email": email}


class LitellmRbacReconcileTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def run_main(self, gateway, members, keep=("platformadmin", "default_user_id")):
        environ = {
            "LITELLM_PORT": "4000",
            "LITELLM_MASTER_KEY": "sk-master",
            "RBAC_ADMINISTRATORS": json.dumps(members),
            "LITELLM_RBAC_KEEP": json.dumps(list(keep)),
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(environ, opener=gateway)
        return stdout.getvalue().splitlines()

    def test_members_are_promoted_and_other_admins_demoted_across_pages(self):
        gateway = FakeGateway(
            [
                account("alice", "internal_user"),
                account("mallory", "proxy_admin"),
                account("bob", "internal_user_viewer", email="Bob@Example.org"),
            ]
        )

        output = self.run_main(
            gateway, [member("alice"), member("robert", "bob@example.org")]
        )

        self.assertEqual(
            gateway.updates(),
            [
                {"user_id": "alice", "user_role": "proxy_admin"},
                {"user_id": "mallory", "user_role": "internal_user"},
                {"user_id": "bob", "user_role": "proxy_admin"},
            ],
        )
        self.assertEqual(
            output,
            [
                "CHANGED alice proxy_admin",
                "CHANGED mallory internal_user",
                "CHANGED bob proxy_admin",
            ],
        )

    def test_kept_users_and_non_admin_outsiders_are_untouched(self):
        gateway = FakeGateway(
            [
                account("platformadmin", "proxy_admin"),
                account("default_user_id", "proxy_admin"),
                account("carol", "internal_user"),
                account("team-bot", "team"),
            ]
        )

        self.assertEqual(self.run_main(gateway, []), ["UNCHANGED"])
        self.assertEqual(gateway.updates(), [])

    def test_every_request_carries_the_master_key_and_targets_the_loopback(self):
        gateway = FakeGateway([account("alice", "internal_user")])
        self.run_main(gateway, [member("alice")])

        for request in gateway.requests:
            self.assertEqual(request.get_header("Authorization"), "Bearer sk-master")
            self.assertTrue(request.full_url.startswith("http://127.0.0.1:4000/"))


if __name__ == "__main__":
    unittest.main()
