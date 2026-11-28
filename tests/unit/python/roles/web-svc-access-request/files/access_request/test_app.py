from __future__ import annotations

import base64
import importlib
import io
import json
import re
import sys
import unittest
import unittest.mock as mock
import urllib.parse

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-access-request" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

app = importlib.import_module("access_request.app")
delivery = importlib.import_module("access_request.delivery")
keycloak = importlib.import_module("access_request.keycloak")
store = importlib.import_module("access_request.store")

PLATFORM = "/roles/web-svc-access-request/administrator"
ROLES = [
    {
        "id": "user",
        "role": "user",
        "tenant": "",
        "description": "Uses",
        "path": "/roles/web-app-x/user",
        "administrator": False,
    },
    {
        "id": "administrator",
        "role": "administrator",
        "tenant": "",
        "description": "Runs",
        "path": "/roles/web-app-x/administrator",
        "administrator": True,
    },
]
TEXTS = {
    key: key
    for key in [
        "form_title",
        "form_application",
        "form_roles",
        "form_administrator",
        "form_reason",
        "form_reason_required",
        "form_submit",
        "form_created",
        "form_updated",
        "form_unknown_application",
        "review_title",
        "review_requester",
        "review_current_groups",
        "review_added_groups",
        "review_confirm",
        "review_reject",
        "review_waiting_second",
        "review_same_approver",
        "review_granted",
        "review_rejected",
        "review_not_allowed",
        "review_console",
        "signin_title",
        "signin_text",
        "signin_action",
        "signout_action",
    ]
}
TEXTS.update(
    {
        "dir": "ltr",
        "mail_request_subject": "request {application} {requester}",
        "mail_granted_subject": "granted {application}",
        "mail_partial_subject": "partial {application}",
        "mail_rejected_subject": "rejected {application}",
    }
)
SIGNOUT_URL = (
    "/oauth2/sign_out?rd=https%3A//auth.example.org/realms/realm"
    "/protocol/openid-connect/logout"
)
SIGNOUT_LINK = f'id="signout" href="{SIGNOUT_URL}">signout_action</a>'
CONFIG = {
    "public_url": "https://access.example.org",
    "signout_url": SIGNOUT_URL,
    "four_eyes": False,
    "platform_group": PLATFORM,
    "approver_emails": ["admin@example.org"],
    "ca_file": "",
    "catalogue": {"web-app-x": {"roles": ROLES, "default": "user"}},
    "i18n": {"en": TEXTS},
    "rbac_i18n": {"en": {}},
}


def _token(sub: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=")
    return "e30." + payload.decode() + ".sig"


def _headers(sub: str, username: str, groups: str = "") -> dict[str, str]:
    return {
        "HTTP_X_FORWARDED_ACCESS_TOKEN": _token(sub),
        "HTTP_X_FORWARDED_PREFERRED_USERNAME": username,
        "HTTP_X_FORWARDED_EMAIL": f"{username}@example.org",
        "HTTP_X_FORWARDED_GROUPS": groups,
    }


class _Mail:
    def __init__(self):
        self.sent = []

    def send(self, recipients, subject, body):
        self.sent.append((recipients, subject, body))


class TestService(unittest.TestCase):
    def setUp(self):
        self.mail = _Mail()
        self.store = store.Store(":memory:")
        self.service = app.Service(
            {**CONFIG},
            self.store,
            self.mail,
            delivery.Zammad(url="", token="", group="Users", ca_file=""),
            keycloak.Realm(
                "https://auth.example.org",
                "realm",
                "https://auth.example.org/admin/realm/console",
                "",
            ),
        )

    def call(self, method, path, headers, fields=None, query=""):
        body = urllib.parse.urlencode(fields or {}, doseq=True).encode()
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
            **headers,
        }
        status = []
        page = b"".join(self.service(environ, lambda s, h: status.append(s))).decode()
        return status[0], page

    def submit(self, roles, requester="sub-biber"):
        return self.call(
            "POST",
            "/",
            _headers(requester, "biber"),
            {
                "application": "web-app-x",
                "roles": roles,
                "reason": "need it",
                "requester": "sub-admin",
            },
        )

    def test_the_form_preselects_the_default_and_marks_the_administrator_role(self):
        status, page = self.call(
            "GET", "/", _headers("sub-biber", "biber"), query="application=web-app-x"
        )

        self.assertEqual("200 OK", status)
        self.assertIn('id="role-user" value="user" checked', page)
        self.assertNotIn('id="role-administrator" value="administrator" checked', page)
        self.assertIn('data-administrator="true"', page)

    def test_the_form_offers_every_role_with_its_description_as_a_checkbox(self):
        _, page = self.call(
            "GET", "/", _headers("sub-biber", "biber"), query="application=web-app-x"
        )

        for role, description in (("user", "Uses"), ("administrator", "Runs")):
            with self.subTest(role=role):
                self.assertIn(
                    f'type="checkbox" name="roles" id="role-{role}" value="{role}"',
                    page,
                )
                self.assertRegex(
                    page,
                    rf'for="role-{role}">.*?<span class="text-muted">{description}</span>',
                )

    def test_the_review_page_shows_paths_reason_and_the_difference(self):
        _, page = self.submit(["user", "administrator"])
        request_id = page.split("/review/")[1].split('"')[0]
        admin = _headers("sub-admin", "administrator", PLATFORM)
        with mock.patch.object(
            app.keycloak, "user_groups", return_value=["/roles/web-app-x/user"]
        ):
            status, page = self.call("GET", f"/review/{request_id}", admin)

        self.assertEqual("200 OK", status)
        self.assertIn('<span id="requester">biber</span>', page)
        self.assertIn('<span id="application">web-app-x</span>', page)
        self.assertIn('<blockquote id="reason">need it</blockquote>', page)
        for role, path, diff in (
            ("user", "/roles/web-app-x/user", "="),
            ("administrator", "/roles/web-app-x/administrator", "+"),
        ):
            with self.subTest(role=role):
                self.assertRegex(
                    page,
                    rf'<tr data-role="{role}">.*?<code>{path}</code>.*?<td class="diff">{re.escape(diff)}</td>',
                )
                self.assertIn(f'id="grant-{role}" checked>', page)

    def test_a_request_mails_the_approvers_and_belongs_to_the_session_user(self):
        status, page = self.submit(["user", "administrator"])
        request_id = page.split("/review/")[1].split('"')[0]

        self.assertEqual("200 OK", status)
        self.assertEqual("sub-biber", self.store.get(request_id)["requester_sub"])
        self.assertEqual(["admin@example.org"], self.mail.sent[0][0])
        self.assertIn(
            "https://auth.example.org/admin/realm/console/#/realm/users/sub-biber/groups",
            self.mail.sent[0][2],
        )

    def test_a_missing_session_asks_to_sign_in_again(self):
        status, page = self.call("GET", "/", {}, query="application=web-app-x")

        self.assertEqual("401 Unauthorized", status)
        self.assertIn('id="signin"', page)

    def test_every_signed_in_page_links_to_the_gate_sign_out(self):
        biber = _headers("sub-biber", "biber")
        admin = _headers("sub-admin", "administrator", PLATFORM)
        _, submitted = self.submit(["user"])
        request_id = submitted.split("/review/")[1].split('"')[0]
        with mock.patch.object(app.keycloak, "user_groups", return_value=[]):
            pages = {
                "landing without an application": self.call("GET", "/", biber)[1],
                "form": self.call("GET", "/", biber, query="application=web-app-x")[1],
                "submitted": submitted,
                "review": self.call("GET", f"/review/{request_id}", admin)[1],
                "unknown path": self.call("GET", "/elsewhere", biber)[1],
            }

        for name, page in pages.items():
            with self.subTest(page=name):
                self.assertIn(SIGNOUT_LINK, page)

    def test_the_sign_in_pages_offer_no_sign_out(self):
        _, submitted = self.submit(["user"])
        request_id = submitted.split("/review/")[1].split('"')[0]
        admin = _headers("sub-admin", "administrator", PLATFORM)
        with mock.patch.object(
            app.keycloak, "user_groups", side_effect=keycloak.GrantError(401, "expired")
        ):
            pages = {
                "no session": self.call("GET", "/", {}),
                "expired approver token": self.call(
                    "GET", f"/review/{request_id}", admin
                ),
            }

        for name, (status, page) in pages.items():
            with self.subTest(page=name):
                self.assertEqual("401 Unauthorized", status)
                self.assertIn('id="signin"', page)
                self.assertNotIn('id="signout"', page)

    def test_the_platform_administrator_grants_the_kept_roles(self):
        _, page = self.submit(["user", "administrator"])
        request_id = page.split("/review/")[1].split('"')[0]
        admin = _headers("sub-admin", "administrator", PLATFORM)
        with (
            mock.patch.object(app.keycloak, "user_groups", return_value=[]),
            mock.patch.object(
                app.keycloak, "grant", return_value=["/roles/web-app-x/user"]
            ) as grant,
        ):
            status, page = self.call(
                "POST",
                f"/review/{request_id}",
                admin,
                {"action": "confirm", "roles": ["user"]},
            )

        self.assertEqual("200 OK", status)
        self.assertIn('id="granted"', page)
        self.assertEqual(["/roles/web-app-x/user"], grant.call_args.args[3])
        self.assertEqual("partial", self.store.get(request_id)["status"])
        self.assertEqual(["biber@example.org"], self.mail.sent[-1][0])

    def test_a_rejection_grants_nothing_and_tells_the_requester(self):
        _, page = self.submit(["user"])
        request_id = page.split("/review/")[1].split('"')[0]
        admin = _headers("sub-admin", "administrator", PLATFORM)
        with (
            mock.patch.object(app.keycloak, "user_groups", return_value=[]),
            mock.patch.object(app.keycloak, "grant") as grant,
        ):
            _, page = self.call(
                "POST", f"/review/{request_id}", admin, {"action": "reject"}
            )

        self.assertIn('id="rejected"', page)
        grant.assert_not_called()
        self.assertEqual("rejected", self.store.get(request_id)["status"])
        self.assertEqual(
            (["biber@example.org"], "rejected web-app-x"), self.mail.sent[-1][:2]
        )

    def test_an_application_administrator_cannot_keep_the_administrator_role(self):
        _, page = self.submit(["administrator"])
        request_id = page.split("/review/")[1].split('"')[0]
        app_admin = _headers("sub-mapache", "mapache", "/roles/web-app-x/administrator")
        with mock.patch.object(app.keycloak, "user_groups", return_value=[]):
            _, page = self.call(
                "POST",
                f"/review/{request_id}",
                app_admin,
                {"action": "confirm", "roles": ["administrator"]},
            )

        self.assertIn('id="not-allowed"', page)

    def test_with_four_eyes_the_first_confirmation_waits_for_a_second_approver(self):
        self.service.config["four_eyes"] = True
        _, page = self.submit(["user"])
        request_id = page.split("/review/")[1].split('"')[0]
        admin = _headers("sub-admin", "administrator", PLATFORM)
        with (
            mock.patch.object(app.keycloak, "user_groups", return_value=[]),
            mock.patch.object(app.keycloak, "grant") as grant,
        ):
            _, first = self.call(
                "POST",
                f"/review/{request_id}",
                admin,
                {"action": "confirm", "roles": ["user"]},
            )
            _, again = self.call(
                "POST",
                f"/review/{request_id}",
                admin,
                {"action": "confirm", "roles": ["user"]},
            )

        self.assertIn('id="waiting"', first)
        self.assertIn('id="same-approver"', again)
        grant.assert_not_called()

    def test_an_expired_approver_token_asks_to_sign_in_again(self):
        _, page = self.submit(["user"])
        request_id = page.split("/review/")[1].split('"')[0]
        admin = _headers("sub-admin", "administrator", PLATFORM)
        with mock.patch.object(
            app.keycloak, "user_groups", side_effect=keycloak.GrantError(401, "expired")
        ):
            status, page = self.call("GET", f"/review/{request_id}", admin)

        self.assertEqual("401 Unauthorized", status)
        self.assertIn('id="signin"', page)


if __name__ == "__main__":
    unittest.main()
