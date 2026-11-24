from __future__ import annotations

import json
import unittest
import urllib.parse

from provider.linkedin import Client, LinkedIn, Request, plain_text
from provider.store import Store

CLIENT_ID = "simulator-linkedin"
SECRET = "simulator-linkedin-secret"
CALLBACK = "https://publish.example/api/v1/accounts/linkedin/callback"
AUTHORIZE = {
    "response_type": "code",
    "client_id": CLIENT_ID,
    "redirect_uri": CALLBACK,
    "scope": "openid profile w_member_social",
    "state": "state-1",
}


def form(
    method: str, path: str, fields: dict[str, str], headers: dict | None = None
) -> Request:
    return Request(
        method, path, {}, headers or {}, urllib.parse.urlencode(fields).encode()
    )


def call(
    method: str, path: str, token: str, body: object = None, query: dict | None = None
) -> Request:
    return Request(
        method,
        path,
        query or {},
        {"authorization": f"Bearer {token}"},
        json.dumps(body).encode() if body is not None else b"",
    )


class Fixture:
    def setUp(self) -> None:
        self.app = LinkedIn(
            Store(), {CLIENT_ID: Client(SECRET, "OpenPost", (CALLBACK,))}
        )

    def sign_up(self, email: str = "ada@example.org") -> None:
        response = self.app.handle(
            form(
                "POST",
                "/signup",
                {"name": "Ada Lovelace", "email": email, "password": "pw", "next": ""},
            )
        )
        self.assertEqual(response.status, 201)

    def code(self, email: str = "ada@example.org") -> str:
        response = self.app.handle(
            form(
                "POST",
                "/oauth/v2/authorization",
                {**AUTHORIZE, "email": email, "password": "pw", "decision": "allow"},
            )
        )
        self.assertEqual(response.status, 302)
        location = urllib.parse.urlsplit(response.headers["Location"])
        query = dict(urllib.parse.parse_qsl(location.query))
        self.assertEqual(query["state"], "state-1")
        self.assertTrue(response.headers["Location"].startswith(CALLBACK + "?"))
        return query["code"]

    def tokens(self) -> dict:
        self.sign_up()
        response = self.app.handle(
            form(
                "POST",
                "/oauth/v2/accessToken",
                {
                    "grant_type": "authorization_code",
                    "code": self.code(),
                    "redirect_uri": CALLBACK,
                    "client_id": CLIENT_ID,
                    "client_secret": SECRET,
                },
            )
        )
        self.assertEqual(response.status, 200)
        return json.loads(response.body)


class TestSignUpAndConsent(Fixture, unittest.TestCase):
    def test_the_sign_up_page_offers_a_form(self) -> None:
        page = self.app.handle(Request("GET", "/signup", {"next": ""}, {}, b""))
        self.assertEqual(page.status, 200)
        self.assertIn(b"Create account", page.body)

    def test_a_sign_up_from_the_consent_page_returns_to_it(self) -> None:
        back = "/oauth/v2/authorization?" + urllib.parse.urlencode(AUTHORIZE)
        response = self.app.handle(
            form(
                "POST",
                "/signup",
                {
                    "name": "Ada",
                    "email": "ada@example.org",
                    "password": "pw",
                    "next": back,
                },
            )
        )
        self.assertEqual((response.status, response.headers["Location"]), (303, back))

    def test_a_sign_up_never_redirects_off_the_fake(self) -> None:
        response = self.app.handle(
            form(
                "POST",
                "/signup",
                {
                    "name": "Ada",
                    "email": "ada@example.org",
                    "password": "pw",
                    "next": "https://evil.example/",
                },
            )
        )
        self.assertEqual(response.status, 201)

    def test_the_consent_page_names_the_client_and_its_scopes(self) -> None:
        page = self.app.handle(
            Request("GET", "/oauth/v2/authorization", AUTHORIZE, {}, b"")
        )
        self.assertEqual(page.status, 200)
        self.assertIn(b"OpenPost", page.body)
        self.assertIn(b"w_member_social", page.body)
        self.assertIn(b"/signup?next=", page.body)

    def test_an_unregistered_redirect_uri_is_refused(self) -> None:
        page = self.app.handle(
            Request(
                "GET",
                "/oauth/v2/authorization",
                {**AUTHORIZE, "redirect_uri": "https://evil/cb"},
                {},
                b"",
            )
        )
        self.assertEqual(page.status, 400)

    def test_wrong_credentials_stay_on_the_consent_page(self) -> None:
        self.sign_up()
        response = self.app.handle(
            form(
                "POST",
                "/oauth/v2/authorization",
                {
                    **AUTHORIZE,
                    "email": "ada@example.org",
                    "password": "wrong",
                    "decision": "allow",
                },
            )
        )
        self.assertEqual(response.status, 400)
        self.assertIn(b"Wrong email or password", response.body)

    def test_cancelling_returns_an_error_to_the_client(self) -> None:
        response = self.app.handle(
            form("POST", "/oauth/v2/authorization", {**AUTHORIZE, "decision": "deny"})
        )
        query = dict(
            urllib.parse.parse_qsl(
                urllib.parse.urlsplit(response.headers["Location"]).query
            )
        )
        self.assertEqual(
            query, {"error": "user_cancelled_authorize", "state": "state-1"}
        )


class TestTokens(Fixture, unittest.TestCase):
    def test_a_code_becomes_tokens_that_describe_the_member(self) -> None:
        tokens = self.tokens()
        profile = json.loads(
            self.app.handle(call("GET", "/v2/userinfo", tokens["access_token"])).body
        )
        self.assertEqual(
            (profile["name"], profile["given_name"]), ("Ada Lovelace", "Ada")
        )
        self.assertTrue(profile["sub"])

    def test_a_wrong_client_secret_is_refused(self) -> None:
        self.sign_up()
        response = self.app.handle(
            form(
                "POST",
                "/oauth/v2/accessToken",
                {
                    "grant_type": "authorization_code",
                    "code": self.code(),
                    "redirect_uri": CALLBACK,
                    "client_id": CLIENT_ID,
                    "client_secret": "wrong",
                },
            )
        )
        self.assertEqual(response.status, 401)

    def test_a_refresh_token_yields_a_working_access_token(self) -> None:
        tokens = self.tokens()
        response = self.app.handle(
            form(
                "POST",
                "/oauth/v2/accessToken",
                {
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                    "client_id": CLIENT_ID,
                    "client_secret": SECRET,
                },
            )
        )
        refreshed = json.loads(response.body)
        self.assertEqual(
            self.app.handle(
                call("GET", "/v2/userinfo", refreshed["access_token"])
            ).status,
            200,
        )

    def test_an_unknown_token_is_refused(self) -> None:
        self.assertEqual(
            self.app.handle(call("GET", "/v2/userinfo", "nope")).status, 401
        )


class TestPosts(Fixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.token = self.tokens()["access_token"]
        profile = json.loads(
            self.app.handle(call("GET", "/v2/userinfo", self.token)).body
        )
        self.author = f"urn:li:person:{profile['sub']}"

    def post(self, body: dict) -> object:
        return self.app.handle(call("POST", "/rest/posts", self.token, body))

    def body(self, **extra: object) -> dict:
        return {
            "author": self.author,
            "commentary": r"Hello \#world",
            "visibility": "PUBLIC",
            "lifecycleState": "PUBLISHED",
            **extra,
        }

    def test_a_post_is_stored_and_read_back_by_its_id(self) -> None:
        response = self.post(self.body())
        self.assertEqual(response.status, 201)
        post_id = response.headers["x-restli-id"]
        read = self.app.handle(
            call(
                "GET", f"/rest/posts/{urllib.parse.quote(post_id, safe='')}", self.token
            )
        )
        self.assertEqual(json.loads(read.body)["commentary"], r"Hello \#world")

    def test_the_feed_page_shows_the_unescaped_text_without_a_token(self) -> None:
        post_id = self.post(self.body()).headers["x-restli-id"]
        page = self.app.handle(Request("GET", f"/feed/update/{post_id}", {}, {}, b""))
        self.assertEqual(page.status, 200)
        self.assertIn(b"Hello #world", page.body)
        self.assertIn(b"Ada Lovelace on LinkedIn", page.body)

    def test_posting_as_someone_else_is_refused(self) -> None:
        self.assertEqual(self.post(self.body(author="urn:li:person:other")).status, 403)

    def test_an_image_post_needs_an_uploaded_image(self) -> None:
        initialized = self.app.handle(
            call(
                "POST",
                "/rest/images",
                self.token,
                {"initializeUploadRequest": {"owner": self.author}},
                {"action": "initializeUpload"},
            )
        )
        value = json.loads(initialized.body)["value"]
        media = {"content": {"media": {"id": value["image"]}}}
        self.assertEqual(self.post(self.body(**media)).status, 422)
        upload_path = urllib.parse.urlsplit(value["uploadUrl"]).path
        self.assertEqual(
            self.app.handle(
                Request(
                    "PUT",
                    upload_path,
                    {},
                    {"authorization": f"Bearer {self.token}"},
                    b"\xff\xd8",
                )
            ).status,
            201,
        )
        self.assertEqual(self.post(self.body(**media)).status, 201)

    def test_the_admin_listing_shows_posts_with_plain_text(self) -> None:
        self.post(self.body())
        posts = json.loads(
            self.app.handle(Request("GET", "/__fake/linkedin/posts", {}, {}, b"")).body
        )
        self.assertEqual([post["text"] for post in posts], ["Hello #world"])


class TestPlainText(unittest.TestCase):
    def test_linkedin_markup_escapes_are_removed(self) -> None:
        self.assertEqual(
            plain_text(r"a \#tag \@name \(x\) \\ end"), r"a #tag @name (x) \ end"
        )


if __name__ == "__main__":
    unittest.main()
