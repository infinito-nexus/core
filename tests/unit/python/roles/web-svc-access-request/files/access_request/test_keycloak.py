from __future__ import annotations

import importlib
import io
import json
import sys
import unittest
import unittest.mock as mock
import urllib.error

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-access-request" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

keycloak = importlib.import_module("access_request.keycloak")

REALM = keycloak.Realm(
    base_url="https://auth.example.org/",
    realm="infinito nexus",
    console_url="https://auth.example.org/admin/infinito/console",
    ca_file="",
)
GROUP_IDS = {
    "roles/web-app-blog/editor": "g-editor",
    "roles/web-app-blog/subscriber": "g-subscriber",
}


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Keycloak:
    """Answers the admin REST calls the module makes and records them."""

    def __init__(self, refused=(), status=403):
        self.calls = []
        self.refused = set(refused)
        self.status = status

    def __call__(self, request, timeout, context):
        url = request.full_url
        self.calls.append((request.get_method(), url, request.headers["Authorization"]))
        base = "https://auth.example.org/admin/realms/infinito%20nexus/"
        path = url.removeprefix(base)
        if path.startswith("group-by-path/"):
            group = path.removeprefix("group-by-path/")
            return _Answer(json.dumps({"id": GROUP_IDS[group]}).encode())
        if request.get_method() == "PUT":
            if path.rsplit("/", 1)[1] in self.refused:
                raise urllib.error.HTTPError(url, self.status, "refused", {}, None)
            return _Answer(b"")
        if path.startswith("users/") and "/groups" in path:
            return _Answer(
                json.dumps(
                    [{"path": "/roles/web-app-b/user"}, {"path": "/roles/web-app-a/x"}]
                ).encode()
            )
        raise AssertionError(f"unexpected call {request.get_method()} {url}")


class TestGrant(unittest.TestCase):
    def test_every_accepted_group_is_joined_with_the_approver_token(self):
        fake = _Keycloak()
        with mock.patch.object(keycloak.urllib.request, "urlopen", fake):
            accepted = keycloak.grant(
                REALM,
                "approver-token",
                "sub-biber",
                ["/roles/web-app-blog/editor", "/roles/web-app-blog/subscriber"],
            )

        self.assertEqual(
            ["/roles/web-app-blog/editor", "/roles/web-app-blog/subscriber"], accepted
        )
        self.assertIn(
            (
                "PUT",
                "https://auth.example.org/admin/realms/infinito%20nexus/users/sub-biber/groups/g-editor",
                "Bearer approver-token",
            ),
            fake.calls,
        )
        self.assertEqual({"Bearer approver-token"}, {call[2] for call in fake.calls})

    def test_a_group_keycloak_refuses_is_left_out(self):
        fake = _Keycloak(refused={"g-editor"})
        with mock.patch.object(keycloak.urllib.request, "urlopen", fake):
            accepted = keycloak.grant(
                REALM,
                "t",
                "sub-biber",
                ["/roles/web-app-blog/editor", "/roles/web-app-blog/subscriber"],
            )

        self.assertEqual(["/roles/web-app-blog/subscriber"], accepted)

    def test_an_expired_token_aborts_the_grant(self):
        fake = _Keycloak(refused={"g-editor"}, status=401)
        with (
            mock.patch.object(keycloak.urllib.request, "urlopen", fake),
            self.assertRaises(keycloak.GrantError) as raised,
        ):
            keycloak.grant(REALM, "t", "sub-biber", ["/roles/web-app-blog/editor"])

        self.assertEqual(401, raised.exception.status)


class TestReads(unittest.TestCase):
    def test_the_live_groups_come_back_sorted(self):
        with mock.patch.object(keycloak.urllib.request, "urlopen", _Keycloak()):
            groups = keycloak.user_groups(REALM, "t", "sub-biber")

        self.assertEqual(["/roles/web-app-a/x", "/roles/web-app-b/user"], groups)

    def test_the_console_link_opens_the_users_groups_tab(self):
        self.assertEqual(
            "https://auth.example.org/admin/infinito/console/#/infinito%20nexus/users/sub-biber/groups",
            REALM.user_groups_console("sub-biber"),
        )


if __name__ == "__main__":
    unittest.main()
