from __future__ import annotations

import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from openpost.api import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    CONTAINER,
    DEADLINE,
    MAIL_RECIPIENT,
    ONION_ORIGIN,
    OPENER,
    PEERTUBE_PASSWORD,
    PEERTUBE_USERNAME,
    PUBLIC_URL,
    RELAY_TARGETS,
    S3_PUBLIC_URL,
    SETTLE_SECONDS,
    SIMULATOR_PLATFORMS,
    SMTP_ENABLED,
    SSO_ADMIN_EMAIL,
    SSO_ENABLED,
    UNCONFIGURED_PLATFORMS,
    anonymous_jpeg,
    call,
    check,
    draft,
    failures,
    in_container,
    public_url,
    release,
    revoke_invitations,
    settle,
    team,
    upload,
)
from openpost.crossposter import ROUTES, check_crossposter
from openpost.simulator import check_simulator

PRIVATE_TARGETS = ("https://postgres", "https://10.0.0.1")
SQLITE_PATTERNS = (
    "-name",
    "*.sqlite",
    "-o",
    "-name",
    "*.sqlite3",
    "-o",
    "-name",
    "*.db",
)


def wait_ready() -> None:
    while True:
        try:
            status, _ = call("GET", "/ready")
            if status == 200:
                return
        except OSError:
            pass
        if time.monotonic() > DEADLINE:
            sys.exit("[FAIL] OpenPost never reported ready")
        time.sleep(5)


def login() -> str:
    status, body = call(
        "POST", "/auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    if status != 200 or not isinstance(body, dict) or not body.get("token"):
        sys.exit(f"[FAIL] break-glass login returned HTTP {status}")
    print("[OK]   break-glass instance admin signs in")
    return str(body["token"])


def flag(path: str, key: str) -> object:
    status, body = call("GET", path)
    if status != 200 or not isinstance(body, dict):
        return f"HTTP {status}"
    return body.get(key)


def public_status(method: str, path: str) -> int:
    request = urllib.request.Request(PUBLIC_URL + path, data=b"{}", method=method)  # noqa: S310 fixed public OpenPost origin
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 fixed public OpenPost origin
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def anonymous_get(path: str) -> int:
    request = urllib.request.Request(PUBLIC_URL + path)  # noqa: S310 fixed public OpenPost origin
    try:
        with OPENER.open(request, timeout=60) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def check_access() -> None:
    status = anonymous_get("/api/v1/accounts/mastodon/callback")
    check(
        "the provider callback answers without a session",
        status in (302, 303, 307),
        f"HTTP {status}",
    )
    status = anonymous_get("/api/v1/workspaces")
    check("the API refuses anonymous requests", status == 401, f"HTTP {status}")
    found = in_container(
        CONTAINER,
        "find",
        "/",
        "(",
        "-path",
        "/proc",
        "-o",
        "-path",
        "/sys",
        ")",
        "-prune",
        "-o",
        "-type",
        "f",
        "(",
        *SQLITE_PATTERNS,
        ")",
        "-print",
        user="0",
    )
    check(
        "no SQLite database exists in the container",
        not found.strip(),
        found.decode()[:400],
    )


def check_sso_administrator(token: str) -> None:
    status, body = call("GET", "/admin/users?per_page=100", token=token)
    users = body.get("users") if status == 200 and isinstance(body, dict) else None
    found = [
        user
        for user in users or []
        if str(user.get("email")).lower() == SSO_ADMIN_EMAIL.lower()
    ]
    check(
        "the SSO administrator from the bootstrap allowlist is an instance admin",
        bool(found) and found[0].get("is_admin") is True,
        found,
    )
    mastodon = RELAY_TARGETS.get("mastodon")
    if found and mastodon and not mastodon.endswith(".onion"):
        count = found[0].get("publication_count")
        check(
            "the SSO administrator's publications survived the backup drill",
            isinstance(count, int) and count >= 1,
            count,
        )


def check_data_minimisation() -> None:
    for label, path, key in (
        ("PostHog telemetry is off", "/telemetry/config", "enabled"),
        ("diagnostics reports are off", "/diagnostics/public-config", "enabled"),
        ("public profiles are off", "/auth/config", "public_profiles_enabled"),
    ):
        value = flag(path, key)
        check(label, value is False, f"{path} {key}={value!r}")
    if SSO_ENABLED:
        status = public_status("POST", "/api/v1/auth/register")
        check(
            "the proxy refuses password self-registration",
            status == 403,
            f"HTTP {status}",
        )
    else:
        value = flag("/auth/config", "registration_enabled")
        check(
            "password self-registration is off",
            value is False,
            f"registration_enabled={value!r}",
        )


def workspace_id(token: str) -> str:
    status, body = call("GET", "/workspaces", token=token)
    if status == 200 and isinstance(body, list) and body:
        return str(body[0]["id"])
    status, body = call("POST", "/workspaces", {"name": "CLI probe"}, token=token)
    if status != 200 or not isinstance(body, dict):
        sys.exit(f"[FAIL] cannot create a probe workspace: HTTP {status}")
    return str(body["id"])


def auth_url(
    token: str, workspace: str, platform: str, instance_url: str
) -> tuple[int, object]:
    query = urllib.parse.urlencode(
        {"workspace_id": workspace, "instance_url": instance_url}
    )
    return call("GET", f"/accounts/{platform}/auth-url?{query}", token=token)


def check_unconfigured(token: str, workspace: str) -> None:
    for platform in UNCONFIGURED_PLATFORMS:
        status, body = call(
            "GET",
            f"/accounts/{platform}/auth-url?workspace_id={workspace}",
            token=token,
        )
        check(
            f"{platform} cannot be connected without provider credentials",
            status != 200,
            f"HTTP {status} {body}",
        )


def check_relay(token: str, workspace: str) -> None:
    for platform, domain in RELAY_TARGETS.items():
        if platform == "peertube":
            continue
        if domain.endswith(".onion"):
            print(
                f"[SKIP] relay to {platform}: OpenPost cannot resolve the onion name {domain}"
            )
            continue
        status, body = auth_url(token, workspace, platform, f"https://{domain}")
        check(
            f"relay carries {platform} at {domain} past the guard",
            status == 200,
            f"HTTP {status} {body}",
        )
    for target in PRIVATE_TARGETS:
        status, body = auth_url(token, workspace, "mastodon", target)
        check(f"guard still rejects {target}", status != 200, f"HTTP {status} {body}")


def check_media(token: str, workspace: str) -> None:
    media, key = upload(token, workspace, "image")
    publication = draft(
        token, workspace, [], f"Media probe {media}", "image", media, {}, ""
    )
    attached: dict = {}
    budget = min(DEADLINE, time.monotonic() + 60)
    while not attached.get("public_url_checked_at") and time.monotonic() < budget:
        status, body = call("GET", f"/publications/{publication['id']}", token=token)
        attached = (
            (body.get("media") if status == 200 and isinstance(body, dict) else None)
            or [{}]
        )[0]
        time.sleep(0 if attached.get("public_url_checked_at") else 3)
    if ONION_ORIGIN:
        check(
            "OpenPost flags media on an onion origin as unreachable for providers",
            attached.get("public_url_ready") is False
            and "OPENPOST_MEDIA_URL" in str(attached.get("public_url_error")),
            attached,
        )
    else:
        check(
            "OpenPost reaches the public URL of uploaded media without a session",
            attached.get("public_url_ready") is True
            and attached.get("public_url_status") == 200,
            attached,
        )
    if S3_PUBLIC_URL:
        check(
            f"uploaded media lands in S3 and is fetchable anonymously under {S3_PUBLIC_URL}",
            anonymous_jpeg(S3_PUBLIC_URL + key),
            key,
        )
    else:
        check(
            "uploaded media is served under /media/",
            str(attached.get("url")).startswith("/media/"),
            attached.get("url"),
        )
    call("DELETE", f"/publications/{publication['id']}", token=token)


def check_mail(token: str, workspace: str) -> None:
    revoke_invitations(token, workspace, MAIL_RECIPIENT)
    status, invitation = call(
        "POST",
        f"/workspaces/{workspace}/invitations",
        {"email": MAIL_RECIPIENT, "role": "viewer"},
        token,
    )
    if status != 200 or not isinstance(invitation, dict):
        check("OpenPost sends an invitation mail", False, f"HTTP {status} {invitation}")
        return
    state = str(invitation["email_delivery_status"])
    while state in ("created", "queued") and time.monotonic() < DEADLINE:
        time.sleep(5)
        current = [
            item
            for item in team(token, workspace).get("invitations") or []
            if item["id"] == invitation["id"]
        ]
        state = str(current[0]["email_delivery_status"]) if current else "revoked"
    call(
        "DELETE", f"/workspaces/{workspace}/invitations/{invitation['id']}", token=token
    )
    check(
        "OpenPost hands an invitation mail to the platform mail server",
        state in ("sent", "delivered"),
        state,
    )


def peertube_has(domain: str, tag: str) -> bool:
    query = urllib.parse.urlencode({"count": 25, "sort": "-publishedAt"})
    try:
        with OPENER.open(
            public_url(f"https://{domain}")
            + f"/api/v1/accounts/{PEERTUBE_USERNAME}/videos?{query}",
            timeout=60,
        ) as response:
            videos = json.loads(response.read().decode()).get("data") or []
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return any(tag in str(video.get("name")) for video in videos)


def check_peertube(token: str, workspace: str) -> None:
    domain = RELAY_TARGETS["peertube"]
    credentials = {"username": PEERTUBE_USERNAME, "password": PEERTUBE_PASSWORD}
    status, body = call(
        "POST",
        "/accounts/peertube/login",
        {"workspace_id": workspace, "instance_url": f"https://{domain}", **credentials},
        token,
    )
    if status == 200 and isinstance(body, dict) and body.get("selection_required"):
        choice = [str(option["id"]) for option in body.get("options") or []]
        status, body = call(
            "POST",
            f"/accounts/selections/{body['connection_id']}/complete",
            {"selection_ids": choice},
            token,
        )
    check(
        f"a local PeerTube account at {domain} connects with its password",
        status == 200,
        f"HTTP {status} {body}",
    )
    listed = call("GET", f"/accounts?workspace_id={workspace}", token=token)[1]
    channels = (
        [item for item in listed if item.get("platform") == "peertube"]
        if isinstance(listed, list)
        else []
    )
    if status != 200 or not channels:
        return
    tag = f"openpost-cli-peertube-{secrets.token_hex(4)}"
    media, _ = upload(token, workspace, "video")
    settings = {"channel": channels[0]["account_id"], "title": tag, "privacy": "public"}
    publication = draft(
        token,
        workspace,
        [str(channels[0]["id"])],
        f"PeerTube delivery {tag}",
        "video",
        media,
        settings,
        "",
    )
    status, body = release(token, publication, "publish-now")
    check("the PeerTube video can be published", status == 200, f"HTTP {status} {body}")
    if status != 200:
        return
    current = settle(token, {"peertube": str(publication["id"])}).get("peertube") or [
        {}
    ]
    check(
        "the PeerTube destination ends published",
        current[0].get("status") == "published",
        current[0],
    )
    budget = min(DEADLINE, time.monotonic() + SETTLE_SECONDS)
    while not peertube_has(domain, tag) and time.monotonic() < budget:
        time.sleep(5)
    check("the video appears on the PeerTube instance", peertube_has(domain, tag), tag)


def main() -> int:
    wait_ready()
    print("[OK]   /api/v1/ready answers 200")
    token = login()
    check_data_minimisation()
    check_access()
    if SSO_ADMIN_EMAIL:
        check_sso_administrator(token)
    workspace = workspace_id(token)
    check_relay(token, workspace)
    check_unconfigured(token, workspace)
    check_media(token, workspace)
    if MAIL_RECIPIENT and SMTP_ENABLED:
        check_mail(token, workspace)
    if SIMULATOR_PLATFORMS:
        check_simulator(token, workspace)
    if RELAY_TARGETS.get("peertube", "").endswith(".onion"):
        print("[SKIP] PeerTube connect: OpenPost cannot resolve an onion PeerTube")
    elif "peertube" in RELAY_TARGETS:
        check_peertube(token, workspace)
    if ROUTES and ONION_ORIGIN:
        print(
            "[SKIP] crossposter delivery: an onion OpenPost can neither hand media to providers nor connect onion Fediverse targets"
        )
    elif ROUTES:
        check_crossposter(token, workspace)
    if failures:
        print(f"[FAIL] {len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
