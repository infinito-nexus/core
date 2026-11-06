"""Env (rendered into test.env from templates/test.env.j2):
OPENPOST_LOCAL_URL           published OpenPost origin on the stack host
OPENPOST_API_HEADERS_B64     base64 JSON of the Host and proto headers the proxy would send
OPENPOST_ADMIN_EMAIL         break-glass instance admin e-mail
OPENPOST_ADMIN_PASSWORD_B64  base64 break-glass password
OPENPOST_RELAY_TARGETS       JSON map of sibling platform to the domain the relay carries
OPENPOST_DEADLINE_SECONDS    readiness budget, below the harness timeout
OPENPOST_PUBLIC_URL          public origin served by the shared proxy
OPENPOST_SSO_ENABLED         true when Keycloak provisions users, so the proxy closes password sign-up
OPENPOST_CONTAINER           resolved OpenPost container, used to reach the simulator admin API
OPENPOST_SIMULATOR_PLATFORMS JSON list of OpenPost platforms served by the provider simulator, empty without it
OPENPOST_SIMULATOR_HOST      one simulator alias, whose /__admin API holds the request journal
OPENPOST_PROVIDER_URL        published plain-HTTP origin of the fake provider that plays LinkedIn, empty without it
OPENPOST_UNCONFIGURED_PLATFORMS JSON list of commercial platforms without credentials, which must not connect
OPENPOST_S3_PUBLIC_URL       public bucket URL with a trailing slash, empty when media stays in the role volume
OPENPOST_DB_CONTAINER        resolved Postgres container
OPENPOST_DB_NAME             OpenPost database name
OPENPOST_DB_USER             OpenPost database user
OPENPOST_DB_PASSWORD_B64     base64 OpenPost database password
OPENPOST_MAIL_RECIPIENT      platform mailbox that receives a probe invitation, empty without mail
OPENPOST_SMTP_ENABLED        true when OpenPost itself is given an SMTP relay it can use
OPENPOST_SSO_ADMIN_EMAIL     platform administrator the Playwright run provisions through SSO before the backup drill, empty without SSO
OPENPOST_PEERTUBE_USERNAME   local PeerTube account OpenPost connects through its password login
OPENPOST_PEERTUBE_PASSWORD_B64  base64 password of that PeerTube account
OPENPOST_MEMBER_EMAIL        deliverable plus-address of the administrator mailbox for the probe's workspace member
OPENPOST_MEMBER_PASSWORD_B64 base64 password of the probe's workspace member, stable across credential rotation
OPENPOST_PROXY_ADDRESS       stack host address that serves every public vhost, empty when the probe runs on that host's network
"""

from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def public_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if (parts.hostname or "").endswith(".onion") and parts.scheme == "https":
        return urllib.parse.urlunsplit(("http", *parts[1:]))
    return url


BASE = os.environ["OPENPOST_LOCAL_URL"].rstrip("/") + "/api/v1"
HEADERS = json.loads(base64.b64decode(os.environ["OPENPOST_API_HEADERS_B64"]))
ADMIN_EMAIL = os.environ["OPENPOST_ADMIN_EMAIL"]
ADMIN_PASSWORD = base64.b64decode(os.environ["OPENPOST_ADMIN_PASSWORD_B64"]).decode()
RELAY_TARGETS = json.loads(os.environ["OPENPOST_RELAY_TARGETS"])
DEADLINE = time.monotonic() + int(os.environ["OPENPOST_DEADLINE_SECONDS"])
PUBLIC_URL = os.environ["OPENPOST_PUBLIC_URL"].rstrip("/")
ONION_ORIGIN = (urllib.parse.urlparse(PUBLIC_URL).hostname or "").endswith(".onion")
SSO_ENABLED = os.environ["OPENPOST_SSO_ENABLED"] == "true"
CONTAINER = os.environ["OPENPOST_CONTAINER"]
SIMULATOR_PLATFORMS = json.loads(os.environ["OPENPOST_SIMULATOR_PLATFORMS"])
UNCONFIGURED_PLATFORMS = json.loads(os.environ["OPENPOST_UNCONFIGURED_PLATFORMS"])
S3_PUBLIC_URL = os.environ["OPENPOST_S3_PUBLIC_URL"]
SIMULATOR_ADMIN = "https://" + os.environ["OPENPOST_SIMULATOR_HOST"] + "/__admin"
PROVIDER_URL = os.environ["OPENPOST_PROVIDER_URL"].rstrip("/")
DB_CONTAINER = os.environ["OPENPOST_DB_CONTAINER"]
DB_NAME = os.environ["OPENPOST_DB_NAME"]
DB_USER = os.environ["OPENPOST_DB_USER"]
DB_PASSWORD = base64.b64decode(os.environ["OPENPOST_DB_PASSWORD_B64"]).decode()
MAIL_RECIPIENT = os.environ["OPENPOST_MAIL_RECIPIENT"]
SMTP_ENABLED = os.environ["OPENPOST_SMTP_ENABLED"] == "true"
SSO_ADMIN_EMAIL = os.environ["OPENPOST_SSO_ADMIN_EMAIL"]
PEERTUBE_USERNAME = os.environ["OPENPOST_PEERTUBE_USERNAME"]
PEERTUBE_PASSWORD = base64.b64decode(
    os.environ["OPENPOST_PEERTUBE_PASSWORD_B64"]
).decode()
MEMBER_USERNAME = "openpost-cli-member"
MEMBER_PASSWORD = base64.b64decode(os.environ["OPENPOST_MEMBER_PASSWORD_B64"]).decode()
MEMBER_EMAIL = os.environ["OPENPOST_MEMBER_EMAIL"]
PROXY_ADDRESS = os.environ["OPENPOST_PROXY_ADDRESS"]

SETTLE_SECONDS = 300
PROFILES = {"text": "short_text", "image": "image_post", "video": "video"}
ANALYSED = ("ready", "failed")

failures: list[str] = []


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def dial(host: str) -> str:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return PROXY_ADDRESS
    return host


class _ProxyConnection(http.client.HTTPConnection):
    def connect(self) -> None:
        self.sock = socket.create_connection((dial(self.host), self.port), self.timeout)


class _ProxyTlsConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        raw = socket.create_connection((dial(self.host), self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class _ProxyHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_ProxyConnection, req)


class _ProxyTlsHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_ProxyTlsConnection, req, context=self._context)


PROXY_HANDLERS = [_ProxyHandler(), _ProxyTlsHandler()] if PROXY_ADDRESS else []
OPENER = urllib.request.build_opener(_NoRedirect, *PROXY_HANDLERS)
urllib.request.install_opener(urllib.request.build_opener(*PROXY_HANDLERS))


def call(
    method: str, path: str, body: object = None, token: str = ""
) -> tuple[int, object]:
    status, _, payload = call_raw(method, path, body, token)
    return status, payload


def call_raw(
    method: str, path: str, body: object = None, token: str = ""
) -> tuple[int, str, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)  # noqa: S310 fixed OpenPost origin
    for name, value in HEADERS.items():
        request.add_header(name, value)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    return _open(request)


def provider(
    path: str, fields: dict[str, str] | None = None
) -> tuple[int, str, object]:
    data = urllib.parse.urlencode(fields).encode() if fields is not None else None
    request = urllib.request.Request(PROVIDER_URL + path, data=data)  # noqa: S310 fixed fake provider origin
    return _open(request)


def _open(request: urllib.request.Request) -> tuple[int, str, object]:
    try:
        with OPENER.open(request, timeout=60) as response:
            raw = response.read().decode()
            status = response.status
            location = response.headers.get("Location") or ""
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        status = error.code
        location = error.headers.get("Location") or ""
    try:
        return status, location, json.loads(raw) if raw else None
    except ValueError:
        return status, location, raw


def in_container(
    container: str, *argv: str, env: dict[str, str] | None = None, user: str = ""
) -> bytes:
    flags = [
        item
        for name, value in (env or {}).items()
        for item in ("-e", f"{name}={value}")
    ]
    flags += ["-u", user] if user else []
    result = subprocess.run(
        ["container", "exec", *flags, container, *argv],
        capture_output=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        sys.exit(
            f"[FAIL] {argv[0]} in {container} exited {result.returncode}: {result.stderr.decode()[-400:]}"
        )
    return result.stdout


def check(label: str, ok: bool, detail: object = "") -> None:
    print(
        ("[OK]   " if ok else "[FAIL] ")
        + label
        + (f": {detail}" if not ok and detail else "")
    )
    if not ok:
        failures.append(label)


def anonymous_jpeg(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 https media URL issued by OpenPost
            return response.status == 200 and response.read(2) == b"\xff\xd8"
    except (urllib.error.URLError, OSError):
        return False


def accounts(token: str, workspace: str) -> dict[str, list[str]]:
    status, body = call("GET", f"/accounts?workspace_id={workspace}", token=token)
    if status != 200 or not isinstance(body, list):
        sys.exit(f"[FAIL] cannot list connected accounts: HTTP {status}")
    found: dict[str, list[str]] = {}
    for item in sorted(body, key=lambda item: str(item.get("created_at"))):
        found.setdefault(str(item["platform"]), []).append(str(item["id"]))
    return found


def render_media(kind: str) -> tuple[str, str, bytes]:
    nonce = secrets.token_hex(3)
    colour = f"color=c=0x{nonce}"
    if kind == "image":
        name, mime = f"openpost-cli-{nonce}.jpg", "image/jpeg"
        source = ["-f", "lavfi", "-i", f"{colour}:s=1080x1080", "-frames:v", "1"]
    else:
        name, mime = f"openpost-cli-{nonce}.mp4", "video/mp4"
        source = [
            "-f",
            "lavfi",
            "-i",
            f"{colour}:s=720x1280:d=3",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
        ]
    target = f"/tmp/{name}"  # noqa: S108 path inside the OpenPost container
    in_container(CONTAINER, "ffmpeg", "-loglevel", "error", "-y", *source, target)
    content = in_container(CONTAINER, "cat", target)
    in_container(CONTAINER, "rm", "-f", target)
    return name, mime, content


def media_state(token: str, workspace: str, media: str) -> str:
    status, body = call(
        "GET", f"/media?workspace_id={workspace}&limit=200", token=token
    )
    items = body.get("media") if status == 200 and isinstance(body, dict) else None
    for item in items or []:
        if item.get("id") == media:
            return str(item.get("analysis_status"))
    return f"HTTP {status}"


def upload(token: str, workspace: str, kind: str) -> tuple[str, str]:
    name, mime, content = render_media(kind)
    status, session = call(
        "POST",
        "/media/upload-session",
        {
            "workspace_id": workspace,
            "filename": name,
            "mime_type": mime,
            "size": len(content),
        },
        token,
    )
    if status != 200 or not isinstance(session, dict):
        sys.exit(f"[FAIL] upload session for {name} returned HTTP {status}: {session}")
    target = session["upload"]
    url = urllib.parse.urlparse(str(target["url"]))
    headers = dict(target["headers"] or {})
    if url.netloc in ("", urllib.parse.urlparse(PUBLIC_URL).netloc):
        headers.update({**HEADERS, "Authorization": "Bearer " + token})
        url = urllib.parse.urlparse(
            BASE.rsplit("/api/v1", 1)[0]
            + url.path
            + (f"?{url.query}" if url.query else "")
        )
    request = urllib.request.Request(  # noqa: S310 upload URL issued by OpenPost
        url.geturl(), data=content, method=str(target["method"])
    )
    for header, value in headers.items():
        request.add_header(header, value if isinstance(value, str) else value[0])
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 upload URL issued by OpenPost
        if response.status not in (200, 201, 204):
            sys.exit(f"[FAIL] media PUT returned HTTP {response.status}")
    complete = urllib.parse.urlparse(str(session["complete_url"])).path.split(
        "/api/v1", 1
    )[1]
    status, body = call("POST", complete, {"workspace_id": workspace}, token)
    if status != 200:
        sys.exit(
            f"[FAIL] completing the upload of {name} returned HTTP {status}: {body}"
        )
    media = str(session["media_id"])
    while (
        kind == "video"
        and media_state(token, workspace, media) not in ANALYSED
        and time.monotonic() < DEADLINE
    ):
        time.sleep(3)
    return media, str(target["object_key"])


def draft(
    token: str,
    workspace: str,
    targets: list[str],
    text: str,
    kind: str,
    media: str,
    settings: dict,
    at: str,
) -> dict:
    payload: dict[str, object] = {
        "workspace_id": workspace,
        "title": text,
        "content_profile": PROFILES[kind],
        "source_text": text,
        "social_account_ids": targets,
        "renditions": [
            {"social_account_id": account, "settings": settings} for account in targets
        ],
    }
    if media:
        payload["media"] = [{"media_id": media}]
    if at:
        payload["scheduled_at"] = at
    status, body = call("POST", "/publications", payload, token)
    if status != 200 or not isinstance(body, dict):
        sys.exit(f"[FAIL] creating publication {text!r} returned HTTP {status}: {body}")
    return body


def release(token: str, publication: dict, action: str) -> tuple[int, object]:
    return call(
        "POST",
        f"/publications/{publication['id']}/{action}",
        {"expected_revision": publication["revision"]},
        token,
    )


def renditions(token: str, publication: str) -> list[dict]:
    status, body = call("GET", f"/publications/{publication}", token=token)
    found = body.get("renditions") if status == 200 and isinstance(body, dict) else None
    return list(found or [])


def settled(rendition: dict) -> bool:
    return rendition.get("status") == "published" or (
        rendition.get("status") == "failed" and not rendition.get("error_retryable")
    )


def settle(token: str, publications: dict[str, str]) -> dict[str, list[dict]]:
    outcome: dict[str, list[dict]] = {}
    budget = min(DEADLINE, time.monotonic() + SETTLE_SECONDS)
    while len(outcome) < len(publications) and time.monotonic() < budget:
        for label, publication in publications.items():
            if label in outcome:
                continue
            current = renditions(token, publication)
            if current and all(settled(rendition) for rendition in current):
                outcome[label] = current
        if len(outcome) < len(publications):
            time.sleep(5)
    return outcome


def team(token: str, workspace: str) -> dict:
    status, body = call("GET", f"/workspaces/{workspace}/team", token=token)
    if status != 200 or not isinstance(body, dict):
        sys.exit(f"[FAIL] cannot read the workspace team: HTTP {status}")
    return body


def revoke_invitations(token: str, workspace: str, email: str) -> None:
    for invitation in team(token, workspace).get("invitations") or []:
        if invitation["email"] == email and invitation["status"] not in (
            "accepted",
            "revoked",
            "expired",
        ):
            call(
                "DELETE",
                f"/workspaces/{workspace}/invitations/{invitation['id']}",
                token=token,
            )
