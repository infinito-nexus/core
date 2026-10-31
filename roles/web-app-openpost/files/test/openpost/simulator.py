from __future__ import annotations

import json
import secrets
import sys
import time
import urllib.parse

from openpost.api import (
    CONTAINER,
    DB_CONTAINER,
    DB_NAME,
    DB_PASSWORD,
    DB_USER,
    MEMBER_EMAIL,
    MEMBER_PASSWORD,
    MEMBER_USERNAME,
    ONION_ORIGIN,
    SIMULATOR_ADMIN,
    SIMULATOR_PLATFORMS,
    SSO_ENABLED,
    accounts,
    call,
    call_raw,
    check,
    draft,
    in_container,
    provider,
    release,
    renditions,
    revoke_invitations,
    settle,
    upload,
)
from openpost.journal import check_journal, hits

SIMULATOR_TOKENS = (
    "simulator-access-token",
    "simulator-access-secret",
    "simulator-meta-user-token",
    "simulator-page-token",
    "simulator-second-page-token",
    "simulator-google-token",
    "simulator-google-refresh",
    "simulator-tiktok-token",
    "simulator-tiktok-refresh",
)
SCHEDULE_AHEAD_SECONDS = 120
SCENARIOS = (
    ("scheduled", "x", "", "text", {}),
    ("x", "x", "", "text", {}),
    ("x-429", "x", "[simulate-429]", "text", {}),
    ("x-503", "x", "[simulate-503]", "text", {}),
    ("x-400", "x", "[simulate-400]", "text", {}),
    ("facebook", "facebook", "", "text", {}),
    ("instagram", "instagram", "", "image", {}),
    ("linkedin", "linkedin", "", "text", {}),
    (
        "tiktok",
        "tiktok",
        "",
        "image",
        {
            "content_posting_method": "DIRECT_POST",
            "privacy_level": "SELF_ONLY",
            "music_usage_confirmed": True,
        },
    ),
    (
        "youtube",
        "youtube",
        "",
        "video",
        {
            "privacy": "private",
            "category_id": "22",
            "playlist_id": "",
            "self_declared_made_for_kids": False,
            "title": "Simulated YouTube video",
        },
    ),
)


def simulator_admin(path: str, post: bool) -> object:
    argv = ["wget", "-q", "-O", "-", "--no-check-certificate"] + (
        ["--post-data="] if post else []
    )
    raw = in_container(CONTAINER, *argv, SIMULATOR_ADMIN + path)
    return json.loads(raw) if raw.strip() else None


def linkedin_consent(url: str) -> dict[str, str] | str:
    email = f"openpost-cli-{secrets.token_hex(4)}@linkedin.invalid"
    password = secrets.token_urlsafe(18)
    status, _, body = provider(
        "/signup",
        {"name": "OpenPost Probe", "email": email, "password": password, "next": ""},
    )
    if status != 201:
        return f"fake LinkedIn sign-up HTTP {status} {body}"
    carried = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    status, location, body = provider(
        "/oauth/v2/authorization",
        {**carried, "email": email, "password": password, "decision": "allow"},
    )
    answer = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(location).query))
    if status != 302 or "code" not in answer:
        return f"fake LinkedIn consent HTTP {status} {location or body}"
    return {"code": answer["code"], "state": answer.get("state", "")}


def check_linkedin(tag: str) -> None:
    status, _, body = provider("/__fake/linkedin/posts")
    posts = [
        post
        for post in (body if isinstance(body, list) else [])
        if tag in str(post.get("text"))
    ]
    check(
        "the fake LinkedIn holds exactly one post with the tag",
        status == 200 and len(posts) == 1,
        f"HTTP {status} {posts}",
    )


def connect(token: str, workspace: str, platform: str, pick: int) -> str:
    status, body = call(
        "GET", f"/accounts/{platform}/auth-url?workspace_id={workspace}", token=token
    )
    if status != 200 or not isinstance(body, dict):
        return f"auth-url HTTP {status} {body}"
    query = urllib.parse.parse_qs(urllib.parse.urlparse(str(body["url"])).query)
    if platform == "x":
        params = {
            "oauth_token": query["oauth_token"][0],
            "oauth_verifier": "simulator-verifier",
        }
    elif platform == "linkedin":
        consent = linkedin_consent(str(body["url"]))
        if isinstance(consent, str):
            return consent
        params = consent
    else:
        params = {"code": "simulator-code", "state": query["state"][0]}
    status, location, _ = call_raw(
        "GET",
        f"/accounts/{platform}/callback?{urllib.parse.urlencode(params)}",
        token=token,
    )
    if status not in (302, 303, 307) or "failed" in location:
        return f"callback HTTP {status} {location}"
    selection = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get(
        "connection_id"
    )
    if not selection:
        return ""
    status, body = call("GET", f"/accounts/selections/{selection[0]}", token=token)
    if status != 200 or not isinstance(body, dict):
        return f"selection HTTP {status} {body}"
    options = [str(option["id"]) for option in body.get("options") or []]
    if pick >= len(options):
        return f"selection offers {len(options)} option(s), wanted option {pick + 1}"
    status, body = call(
        "POST",
        f"/accounts/selections/{selection[0]}/complete",
        {"selection_ids": [options[pick]]},
        token,
    )
    return "" if status == 200 else f"selection complete HTTP {status} {body}"


def check_tokens_at_rest() -> None:
    if not DB_CONTAINER:
        print(
            "[SKIP] tokens at rest: the database task runs on another swarm node than the probe"
        )
        return
    dump = in_container(
        DB_CONTAINER,
        "pg_dump",
        "--data-only",
        "-h",
        "127.0.0.1",
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        env={"PGPASSWORD": DB_PASSWORD},
    ).decode(errors="replace")
    leaked = [value for value in SIMULATOR_TOKENS if value in dump]
    check(
        "the database holds rows for the connected accounts",
        "openpost_simulator" in dump or "4242" in dump,
    )
    check("no provider token is stored in plaintext", not leaked, leaked)


def member_session() -> tuple[str, str]:
    credentials = {"email": MEMBER_EMAIL, "password": MEMBER_PASSWORD}
    status, body = call(
        "POST",
        "/auth/register",
        {**credentials, "username": MEMBER_USERNAME, "accepted_legal": True},
    )
    if status == 409:
        status, body = call("POST", "/auth/login", credentials)
    if status != 200 or not isinstance(body, dict) or not body.get("token"):
        sys.exit(f"[FAIL] the probe member cannot sign in: HTTP {status}")
    return str(body["token"]), str(body["user"]["id"])


def check_roles(token: str, workspace: str, account: str, tag: str) -> str:
    member, member_id = member_session()
    call("DELETE", f"/workspaces/{workspace}/members/{member_id}", token=token)
    revoke_invitations(token, workspace, MEMBER_EMAIL)
    status, invitation = call(
        "POST",
        f"/workspaces/{workspace}/invitations",
        {"email": MEMBER_EMAIL, "role": "viewer"},
        token,
    )
    if status != 200 or not isinstance(invitation, dict):
        sys.exit(
            f"[FAIL] inviting the probe member returned HTTP {status}: {invitation}"
        )
    secret = urllib.parse.parse_qs(
        urllib.parse.urlparse(str(invitation["accept_url"])).query
    )["token"][0]
    status, body = call(
        "POST", "/workspace-invitations/accept", {"token": secret}, member
    )
    if status != 200:
        sys.exit(
            f"[FAIL] the probe member cannot accept the invitation: HTTP {status} {body}"
        )
    publication = draft(
        token, workspace, [account], f"Member {tag}", "text", "", {}, ""
    )
    status, body = release(member, publication, "publish-now")
    check(
        "a workspace viewer is refused when publishing",
        status == 403,
        f"HTTP {status} {body}",
    )
    status, body = call(
        "PATCH",
        f"/workspaces/{workspace}/members/{member_id}",
        {"role": "editor"},
        token,
    )
    if status != 200:
        sys.exit(
            f"[FAIL] promoting the probe member to editor returned HTTP {status}: {body}"
        )
    status, current = call("GET", f"/publications/{publication['id']}", token=member)
    status, body = release(
        member, current if isinstance(current, dict) else publication, "publish-now"
    )
    check("a workspace editor may publish", status == 200, f"HTTP {status} {body}")
    call("DELETE", f"/workspaces/{workspace}/members/{member_id}", token=token)
    return str(publication["id"]) if status == 200 else ""


def check_failure_paths(
    token: str, workspace: str, x: str, publications: dict, tags: dict, outcome: dict
) -> None:
    if "x-400" in outcome:
        rejected = outcome["x-400"][0]
        check(
            "a permanent X rejection leaves the destination failed with the provider error",
            rejected.get("status") == "failed"
            and rejected.get("error_http_status") == 400
            and (rejected.get("delivery") or {}).get("terminal_reason")
            == "provider_rejected",
            rejected,
        )
        status, body = call(
            "POST",
            f"/publications/{publications['x-400']}/renditions/{x}/retry",
            None,
            token,
        )
        check(
            "the failed X destination can be retried alone",
            status == 200,
            f"HTTP {status} {body}",
        )
        outcome.update(settle(token, {"x-400": publications["x-400"]}))
    if "x-503" in outcome:
        ambiguous = outcome["x-503"][0]
        check(
            "an ambiguous X 503 leaves the destination in manual review instead of resending",
            ambiguous.get("status") == "failed"
            and (ambiguous.get("delivery") or {}).get("recovery_action")
            == "manual_resolution",
            ambiguous,
        )
        resend = draft(
            token, workspace, [x], f"Resent {tags['x-503']}", "text", "", {}, ""
        )
        status, body = release(token, resend, "publish-now")
        check(
            "the post can be published again to that X destination alone",
            status == 200,
            f"HTTP {status} {body}",
        )
        publications["x-503-resend"] = str(resend["id"])
        outcome.update(settle(token, {"x-503-resend": publications["x-503-resend"]}))


def check_simulator(token: str, workspace: str) -> None:
    simulator_admin("/scenarios/reset", post=True)
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1))
    for platform in SIMULATOR_PLATFORMS:
        error = connect(token, workspace, platform, 0)
        check(
            f"{platform} connects through OpenPost's callback against the simulator",
            not error,
            error,
        )
    if "facebook" in SIMULATOR_PLATFORMS:
        error = connect(token, workspace, "facebook", 1)
        check(
            "a second Facebook Page connects through its own callback", not error, error
        )
    connected = accounts(token, workspace)
    if "facebook" in SIMULATOR_PLATFORMS:
        pages = connected.get("facebook") or []
        check(
            "two Facebook Pages connect side by side in one workspace",
            len(pages) >= 2,
            pages,
        )
    nonce = secrets.token_hex(4)
    tags = {label: f"openpost-cli-{label}-{nonce}" for label, *_ in SCENARIOS}
    publications: dict[str, str] = {}
    due = 0.0
    if "x" in connected:
        due = time.time() + SCHEDULE_AHEAD_SECONDS
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(due))
        scheduled = draft(
            token,
            workspace,
            connected["x"][:1],
            f"Scheduled {tags['scheduled']}",
            "text",
            "",
            {},
            at,
        )
        status, body = release(token, scheduled, "schedule")
        check(
            "a post can be scheduled two minutes ahead",
            status == 200,
            f"HTTP {status} {body}",
        )
        states = [
            rendition.get("status")
            for rendition in renditions(token, str(scheduled["id"]))
        ]
        check(
            "the scheduled destination shows the scheduled state",
            states == ["scheduled"],
            states,
        )
        publications["scheduled"] = str(scheduled["id"])
    for label, platform, marker, kind, settings in SCENARIOS:
        if (
            label == "scheduled"
            or platform not in SIMULATOR_PLATFORMS
            or platform not in connected
        ):
            continue
        if ONION_ORIGIN and kind in ("image", "video"):
            print(f"[SKIP] {label}: providers cannot fetch media from an onion origin")
            continue
        targets = (
            connected[platform] if label == "facebook" else connected[platform][:1]
        )
        media = upload(token, workspace, kind)[0] if kind in ("image", "video") else ""
        text = f"{marker} Simulated {platform} delivery {tags[label]}".strip()
        publication = draft(token, workspace, targets, text, kind, media, settings, "")
        status, body = release(token, publication, "publish-now")
        if status != 200:
            sys.exit(f"[FAIL] publish-now for {label} returned HTTP {status}: {body}")
        publications[label] = str(publication["id"])
    if not SSO_ENABLED:
        print(
            "[SKIP] workspace roles: without SSO the role closes self-registration, so no second account can exist"
        )
    elif "x" in connected:
        tags["member"] = f"openpost-cli-member-{nonce}"
        promoted = check_roles(token, workspace, connected["x"][0], tags["member"])
        if promoted:
            publications["member"] = promoted
    outcome = settle(token, publications)
    if "x" in connected:
        check_failure_paths(
            token, workspace, connected["x"][0], publications, tags, outcome
        )
    for label in publications:
        if label in ("x-400", "x-503"):
            continue
        current = outcome.get(label) or [{}]
        states = [rendition.get("status") for rendition in current]
        check(
            f"every {label} destination ends published",
            set(states) == {"published"},
            current,
        )
    journal = simulator_admin(
        "/requests?since=" + urllib.parse.quote(since), post=False
    )
    entries = journal["requests"] if isinstance(journal, dict) else []
    for label in publications:
        if label == "linkedin":
            check_linkedin(tags[label])
        elif label in tags:
            check_journal(entries, label, tags[label])
    if "scheduled" in publications:
        delivered = [
            entry["request"]["loggedDate"] / 1000
            for entry in hits(entries, "POST", "/2/tweets", tags["scheduled"])
        ]
        check(
            "the scheduled post is not delivered before its time",
            bool(delivered) and min(delivered) >= due - 1,
            delivered,
        )
    check_tokens_at_rest()
