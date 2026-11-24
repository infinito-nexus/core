from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import asdict, dataclass

from provider.store import Account, Store, StoreError

API_HOST = "api.linkedin.com"
POST_VISIBILITIES = ("PUBLIC", "CONNECTIONS")
ESCAPED_MARKUP = re.compile(r"\\([|{}@\[\]()<>#\\*_~])")
SHARE_PATH = re.compile(r"^/rest/posts/(?P<id>.+)$")
FEED_PATH = re.compile(r"^/feed/update/(?P<id>.+)$")
UPLOAD_PATH = re.compile(r"^/upload/images/(?P<id>[0-9a-f]+)$")


@dataclass(frozen=True)
class Client:
    secret: str
    name: str
    redirect_uris: tuple[str, ...]


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: bytes

    def form(self) -> dict[str, str]:
        return dict(urllib.parse.parse_qsl(self.body.decode(), keep_blank_values=True))

    def bearer(self) -> str:
        value = self.headers.get("authorization", "")
        return value[7:] if value.lower().startswith("bearer ") else ""


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


def plain_text(commentary: str) -> str:
    return ESCAPED_MARKUP.sub(r"\1", commentary)


def _json(
    status: int, payload: object, headers: dict[str, str] | None = None
) -> Response:
    return Response(
        status,
        {"Content-Type": "application/json", **(headers or {})},
        json.dumps(payload).encode(),
    )


def _error(status: int, code: str, message: str) -> Response:
    return _json(status, {"status": status, "code": code, "message": message})


def _redirect(location: str) -> Response:
    return Response(302, {"Location": location}, b"")


def _page(status: int, title: str, body: str) -> Response:
    document = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title></head><body><main>"
        f"<h1>{html.escape(title)}</h1>{body}</main></body></html>"
    )
    return Response(
        status, {"Content-Type": "text/html; charset=utf-8"}, document.encode()
    )


def _hidden(fields: dict[str, str]) -> str:
    return "".join(
        f"<input type='hidden' name='{html.escape(name)}' value='{html.escape(value)}'>"
        for name, value in fields.items()
    )


def _field(label: str, name: str, kind: str) -> str:
    return (
        f"<label>{html.escape(label)} "
        f"<input type='{kind}' name='{name}' required></label>"
    )


def _with_query(url: str, params: dict[str, str]) -> str:
    joiner = "&" if urllib.parse.urlsplit(url).query else "?"
    return url + joiner + urllib.parse.urlencode(params)


class LinkedIn:
    def __init__(self, store: Store, clients: dict[str, Client]) -> None:
        self.store = store
        self.clients = clients

    def handle(self, request: Request) -> Response:
        routes = {
            ("GET", "/signup"): self.signup_page,
            ("POST", "/signup"): self.signup,
            ("GET", "/oauth/v2/authorization"): self.authorization_page,
            ("POST", "/oauth/v2/authorization"): self.authorize,
            ("POST", "/oauth/v2/accessToken"): self.access_token,
            ("GET", "/v2/userinfo"): self.userinfo,
            ("POST", "/rest/images"): self.initialize_upload,
            ("POST", "/rest/posts"): self.create_post,
            ("GET", "/__fake/health"): self.health,
            ("GET", "/__fake/linkedin/posts"): self.admin_posts,
            ("GET", "/__fake/linkedin/accounts"): self.admin_accounts,
        }
        handler = routes.get((request.method, request.path))
        if handler is not None:
            return handler(request)
        for method, pattern, dynamic in (
            ("GET", SHARE_PATH, self.read_post),
            ("GET", FEED_PATH, self.feed_page),
            ("PUT", UPLOAD_PATH, self.upload),
        ):
            match = pattern.match(request.path)
            if match and request.method == method:
                return dynamic(request, urllib.parse.unquote(match.group("id")))
        return _error(
            404, "NOT_FOUND", f"{request.method} {request.path} is not served"
        )

    def health(self, request: Request) -> Response:
        return Response(200, {"Content-Type": "text/plain"}, b"ok")

    def signup_page(self, request: Request, error: str = "") -> Response:
        notice = f"<p role='alert'>{html.escape(error)}</p>" if error else ""
        form = (
            "<form method='post' action='/signup'>"
            f"{_hidden({'next': request.query.get('next', '')})}"
            f"{_field('Name', 'name', 'text')}{_field('Email', 'email', 'email')}"
            f"{_field('Password', 'password', 'password')}"
            "<button type='submit'>Create account</button></form>"
        )
        return _page(400 if error else 200, "Join LinkedIn", notice + form)

    def signup(self, request: Request) -> Response:
        form = request.form()
        try:
            self.store.create_account(
                form.get("name", ""), form.get("email", ""), form.get("password", "")
            )
        except StoreError as error:
            return self.signup_page(
                Request("GET", "/signup", {"next": form.get("next", "")}, {}, b""),
                str(error),
            )
        destination = form.get("next", "")
        if destination.startswith("/oauth/v2/authorization?"):
            return Response(303, {"Location": destination}, b"")
        return _page(201, "Account created", "<p>Your account is ready.</p>")

    def _client(self, params: dict[str, str]) -> Client | None:
        client = self.clients.get(params.get("client_id", ""))
        if client is None or params.get("redirect_uri", "") not in client.redirect_uris:
            return None
        return client

    def authorization_page(self, request: Request, error: str = "") -> Response:
        params = request.query
        client = self._client(params)
        if client is None or params.get("response_type") != "code":
            return _page(
                400, "Invalid request", "<p>The application is not registered.</p>"
            )
        here = "/oauth/v2/authorization?" + urllib.parse.urlencode(params)
        notice = f"<p role='alert'>{html.escape(error)}</p>" if error else ""
        scopes = "".join(
            f"<li>{html.escape(scope)}</li>"
            for scope in params.get("scope", "").split()
        )
        carried = {
            key: params.get(key, "")
            for key in ("client_id", "redirect_uri", "scope", "state", "response_type")
        }
        form = (
            f"<p>{html.escape(client.name)} would like to access your account.</p>"
            f"<ul>{scopes}</ul>"
            "<form method='post' action='/oauth/v2/authorization'>"
            f"{_hidden(carried)}{_field('Email', 'email', 'email')}"
            f"{_field('Password', 'password', 'password')}"
            "<button type='submit' name='decision' value='allow'>Allow</button>"
            "<button type='submit' name='decision' value='deny' formnovalidate>Cancel</button>"
            "</form>"
            f"<p><a href='/signup?{urllib.parse.urlencode({'next': here})}'>Join now</a></p>"
        )
        return _page(400 if error else 200, "Sign in to LinkedIn", notice + form)

    def authorize(self, request: Request) -> Response:
        form = request.form()
        client = self._client(form)
        if client is None or form.get("response_type") != "code":
            return _page(
                400, "Invalid request", "<p>The application is not registered.</p>"
            )
        redirect_uri, state = form["redirect_uri"], form.get("state", "")
        if form.get("decision") != "allow":
            return _redirect(
                _with_query(
                    redirect_uri,
                    {"error": "user_cancelled_authorize", "state": state},
                )
            )
        account = self.store.authenticate(
            form.get("email", ""), form.get("password", "")
        )
        if account is None:
            carried = {
                key: form.get(key, "")
                for key in (
                    "client_id",
                    "redirect_uri",
                    "scope",
                    "state",
                    "response_type",
                )
            }
            return self.authorization_page(
                Request("GET", "/oauth/v2/authorization", carried, {}, b""),
                "Wrong email or password.",
            )
        code = self.store.issue_code(
            account.member, form["client_id"], redirect_uri, form.get("scope", "")
        )
        return _redirect(_with_query(redirect_uri, {"code": code, "state": state}))

    def access_token(self, request: Request) -> Response:
        form = request.form()
        client = self.clients.get(form.get("client_id", ""))
        if client is None or client.secret != form.get("client_secret", ""):
            return _json(
                401,
                {
                    "error": "invalid_client",
                    "error_description": "Client authentication failed",
                },
            )
        try:
            if form.get("grant_type") == "authorization_code":
                grant = self.store.redeem_code(
                    form.get("code", ""),
                    form["client_id"],
                    form.get("redirect_uri", ""),
                )
                return _json(200, self.store.issue_tokens(grant.member, grant.scope))
            if form.get("grant_type") == "refresh_token":
                return _json(200, self.store.refresh(form.get("refresh_token", "")))
        except StoreError as error:
            return _json(
                400, {"error": "invalid_grant", "error_description": str(error)}
            )
        return _json(
            400,
            {
                "error": "unsupported_grant_type",
                "error_description": "Unsupported grant type",
            },
        )

    def _member(self, request: Request) -> Account | None:
        return self.store.member_for(request.bearer())

    def userinfo(self, request: Request) -> Response:
        account = self._member(request)
        if account is None:
            return _error(
                401,
                "REVOKED_ACCESS_TOKEN",
                "The token used in the request has been revoked by the user",
            )
        given, _, family = account.name.partition(" ")
        return _json(
            200,
            {
                "sub": account.member,
                "name": account.name,
                "given_name": given,
                "family_name": family,
                "picture": "",
                "email": account.email,
                "email_verified": True,
                "locale": {"country": "US", "language": "en"},
            },
        )

    def initialize_upload(self, request: Request) -> Response:
        account = self._member(request)
        if account is None:
            return _error(
                401,
                "REVOKED_ACCESS_TOKEN",
                "The token used in the request has been revoked by the user",
            )
        if request.query.get("action") != "initializeUpload":
            return _error(400, "ILLEGAL_ARGUMENT", "Unsupported action")
        payload = json.loads(request.body or b"{}")
        owner = str((payload.get("initializeUploadRequest") or {}).get("owner", ""))
        if owner != account.urn:
            return _error(
                403, "ACCESS_DENIED", "The owner is not the authenticated member"
            )
        image = self.store.register_image(owner)
        return _json(
            200,
            {
                "value": {
                    "uploadUrlExpiresAt": int((self.store.now() + 3600) * 1000),
                    "uploadUrl": f"https://{API_HOST}/upload/images/{image.upload_id}",
                    "image": image.urn,
                }
            },
        )

    def upload(self, request: Request, upload_id: str) -> Response:
        account = self._member(request)
        if account is None:
            return _error(
                401,
                "REVOKED_ACCESS_TOKEN",
                "The token used in the request has been revoked by the user",
            )
        try:
            self.store.store_upload(upload_id, account.urn, request.body)
        except StoreError as error:
            return _error(404, "NOT_FOUND", str(error))
        return Response(201, {}, b"")

    def create_post(self, request: Request) -> Response:
        account = self._member(request)
        if account is None:
            return _error(
                401,
                "REVOKED_ACCESS_TOKEN",
                "The token used in the request has been revoked by the user",
            )
        payload = json.loads(request.body or b"{}")
        if payload.get("author") != account.urn:
            return _error(
                403, "ACCESS_DENIED", "The author is not the authenticated member"
            )
        visibility = payload.get("visibility")
        if (
            visibility not in POST_VISIBILITIES
            or payload.get("lifecycleState") != "PUBLISHED"
        ):
            return _error(
                422, "UNPROCESSABLE_ENTITY", "Unsupported visibility or lifecycle state"
            )
        content = payload.get("content") or {}
        media = (content.get("media") or {}).get("id")
        if media and not self.store.uploaded(str(media), account.urn):
            return _error(
                422,
                "UNPROCESSABLE_ENTITY",
                "The media was never uploaded by this member",
            )
        post = self.store.create_post(
            account.urn, str(payload.get("commentary", "")), visibility, content
        )
        return Response(201, {"x-restli-id": post.id}, b"")

    def _post_body(self, post_id: str) -> dict | None:
        post = self.store.post(post_id)
        if post is None:
            return None
        return {
            "id": post.id,
            "author": post.author,
            "commentary": post.commentary,
            "visibility": post.visibility,
            "lifecycleState": "PUBLISHED",
            "content": post.content,
            "createdAt": int(post.created_at * 1000),
        }

    def read_post(self, request: Request, post_id: str) -> Response:
        if self._member(request) is None:
            return _error(
                401,
                "REVOKED_ACCESS_TOKEN",
                "The token used in the request has been revoked by the user",
            )
        body = self._post_body(post_id)
        if body is None:
            return _error(404, "NOT_FOUND", f"Post {post_id} does not exist")
        return _json(200, body)

    def feed_page(self, request: Request, post_id: str) -> Response:
        post = self.store.post(post_id)
        if post is None:
            return _page(404, "Post not found", "<p>This post does not exist.</p>")
        member = post.author.rsplit(":", 1)[-1]
        author = self.store.account(member)
        name = author.name if author else member
        return _page(
            200,
            f"{name} on LinkedIn",
            f"<article data-post='{html.escape(post.id)}'><p>{html.escape(plain_text(post.commentary))}</p></article>",
        )

    def admin_posts(self, request: Request) -> Response:
        return _json(
            200,
            [
                {**asdict(post), "text": plain_text(post.commentary)}
                for post in self.store.posts()
            ],
        )

    def admin_accounts(self, request: Request) -> Response:
        return _json(
            200,
            [
                {"member": account.member, "name": account.name, "email": account.email}
                for account in self.store.accounts()
            ],
        )
