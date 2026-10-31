"""Env (rendered into test.env from templates/test.env.j2):
OPENPOST_CROSSPOSTER_ROUTES_B64   base64 JSON list of the deployed routes without their tokens, empty list when the crossposter is off
OPENPOST_CROSSPOSTER_SECRETS_FILE host path of the rendered crossposter secrets, which carry the CI source tokens
OPENPOST_CROSSPOSTER_CONTAINER    crossposter container on the probe's node, empty when swarm placed it elsewhere
OPENPOST_CROSSPOSTER_CONFIG       configuration path inside the crossposter container
OPENPOST_CROSSPOSTER_POLL_SECONDS poll interval of the deployed crossposter
OPENPOST_CROSSPOSTER_RETRY_SECONDS upper bound of the deployed retry budget, from max_attempts and cap_seconds
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import time
import urllib.parse
from pathlib import Path

from openpost.api import DEADLINE, accounts, call, check, render_media
from openpost.journal import hits, statuses
from openpost.mailbox import reports_naming
from openpost.simulator import SCENARIOS, simulator_admin
from openpost.sources import (
    mastodon_post,
    mastodon_statuses,
    peertube_upload,
    pixelfed_post,
)

ROUTES = json.loads(base64.b64decode(os.environ["OPENPOST_CROSSPOSTER_ROUTES_B64"]))
SECRETS_FILE = os.environ["OPENPOST_CROSSPOSTER_SECRETS_FILE"]
CROSSPOSTER = os.environ["OPENPOST_CROSSPOSTER_CONTAINER"]
CONFIG = os.environ["OPENPOST_CROSSPOSTER_CONFIG"]
POLL_SECONDS = int(os.environ["OPENPOST_CROSSPOSTER_POLL_SECONDS"])
RETRY_SECONDS = int(os.environ["OPENPOST_CROSSPOSTER_RETRY_SECONDS"])
QUIET_POLLS = 3
MEMBERS = {
    ("mastodon", "review"): ("x",),
    ("mastodon", "auto"): ("mastodon", "x", "facebook", "instagram"),
    ("pixelfed", "auto"): ("instagram", "x"),
    ("peertube", "auto"): ("youtube",),
}
SETTINGS = {label: settings for label, _, _, _, settings in SCENARIOS if settings}
FORMATS = {"youtube": "youtube.video", "tiktok": "tiktok.photo"}
SQL = (
    "import json, sys, psycopg\n"
    "from crossposter import config\n"
    "dsn = config.load(sys.argv[1]).dsn\n"
    "with psycopg.connect(dsn, autocommit=True) as connection:\n"
    "    cursor = connection.execute(sys.argv[2], json.loads(sys.argv[3]))\n"
    "    rows = cursor.fetchall() if cursor.description else []\n"
    "print(json.dumps([list(map(str, row)) for row in rows]))\n"
)
HELD = (
    "import sys, time, psycopg\n"
    "from crossposter import config\n"
    "with psycopg.connect(config.load(sys.argv[1]).dsn) as connection:\n"
    "    connection.execute('LOCK TABLE crossposter.cursors IN ACCESS EXCLUSIVE MODE')\n"
    "    connection.execute('DELETE FROM crossposter.cursors WHERE route = %s', (sys.argv[2],))\n"
    "    print('held', flush=True)\n"
    "    time.sleep(float(sys.argv[3]))\n"
)


def crossposter(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["container", "exec", CROSSPOSTER, *argv],
        capture_output=True,
        timeout=300,
        check=False,
    )


def sql(statement: str, *parameters: str) -> list[list[str]]:
    result = crossposter(
        "python", "-c", SQL, CONFIG, statement, json.dumps(list(parameters))
    )
    if result.returncode != 0:
        check(f"SQL {statement[:40]}", False, result.stderr.decode()[-400:])
        return []
    return json.loads(result.stdout.decode())


def items(source_url: str) -> list[list[str]]:
    return sql(
        "SELECT network, state, resends, publication_id, last_error"
        " FROM crossposter.items WHERE source_url = %s ORDER BY id",
        source_url,
    )


def publications(token: str, workspace: str, nonce: str) -> list[dict]:
    query = urllib.parse.urlencode(
        {"workspace_id": workspace, "search": nonce, "limit": 50}
    )
    status, body = call("GET", f"/publications?{query}", token=token)
    return body if status == 200 and isinstance(body, list) else []


def wait(probe, ready, budget: float) -> object:
    end = min(DEADLINE, time.monotonic() + budget)
    current = probe()
    while not ready(current) and time.monotonic() < end:
        time.sleep(5)
        current = probe()
    return current


def delivered(publication: dict) -> bool:
    found = publication.get("renditions") or []
    return bool(found) and all(item.get("status") == "published" for item in found)


def social_sets(token: str, workspace: str) -> dict[str, dict]:
    status, body = call("GET", f"/social-sets?workspace_id={workspace}", token=token)
    found = body if status == 200 and isinstance(body, list) else []
    return {str(item["name"]): item for item in found}


def fill_sets(token: str, workspace: str) -> None:
    connected = accounts(token, workspace)
    existing = social_sets(token, workspace)
    for route in ROUTES:
        chosen = existing.get(route["social_set"])
        if chosen is None:
            check(f"route {route['name']}: social set exists", False, route)
            continue
        members = [
            {
                "social_account_id": connected[platform][0],
                "default_settings": SETTINGS.get(platform, {}),
                **(
                    {"default_output_profile": FORMATS[platform]}
                    if platform in SETTINGS
                    else {}
                ),
            }
            for platform in MEMBERS[(route["platform"], route["mode"])]
            if connected.get(platform)
        ]
        status, body = call(
            "PUT",
            f"/social-sets/{chosen['id']}",
            {
                "name": chosen["name"],
                "is_default": bool(chosen.get("is_default")),
                "accounts": members,
            },
            token,
        )
        check(
            f"route {route['name']}: its social set takes {len(members)} target(s)",
            status == 200 and bool(members),
            f"HTTP {status} {body}",
        )


def check_instance() -> None:
    result = crossposter("python", "-m", "crossposter", "health", "--config", CONFIG)
    check(
        "the crossposter reports itself healthy", result.returncode == 0, result.stderr
    )
    second = crossposter(
        "timeout",
        str(POLL_SECONDS + 10),
        "python",
        "-m",
        "crossposter",
        "run",
        "--config",
        CONFIG,
    )
    log = second.stderr.decode()
    check(
        "a second crossposter instance stands by while the first holds the lock",
        "standing by" in log and "lock acquired" not in log,
        log[-400:],
    )


def check_listing(states: set[str]) -> None:
    result = crossposter("python", "-m", "crossposter", "list", "--config", CONFIG)
    table = result.stdout.decode()
    check(
        "the list command shows every crossposted state seen in this run",
        result.returncode == 0 and all(f"\t{state}\t" in table for state in states),
        table[-600:],
    )


def mastodon_scenarios(
    token: str, workspace: str, route: dict, source: str
) -> set[str]:
    base, tag, seen = route["base_url"], route["tags"][0], set()
    if route["mode"] == "review":
        nonce = f"cp-{secrets.token_hex(4)}"
        status = mastodon_post(base, source, f"Review {nonce} #{tag}", None, "")
        check("a reviewed Mastodon status is posted", "error" not in status, status)
        found = wait(
            lambda: publications(token, workspace, nonce),
            bool,
            POLL_SECONDS * 4,
        )
        check(
            "a review route leaves an unscheduled OpenPost draft",
            len(found) == 1 and found[0].get("status") == "draft",
            found,
        )
        seen.add("drafted")
        return seen
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1))
    simulator_admin("/scenarios/reset", post=True)
    nonce = f"cp-{secrets.token_hex(4)}"
    name, mime, image = render_media("image")
    status = mastodon_post(
        base, source, f"Auto {nonce} [simulate-503] #{tag}", (name, mime, image), ""
    )
    check("an automatic Mastodon status is posted", "error" not in status, status)
    targets = len(MEMBERS[("mastodon", "auto")])
    found = wait(
        lambda: publications(token, workspace, nonce),
        lambda found: sum(map(delivered, found)) >= targets,
        POLL_SECONDS * 6 + 300,
    )
    check(
        "an auto route delivers the status to every target of its social set",
        sum(map(delivered, found)) == targets,
        [(item.get("status"), item.get("renditions")) for item in found],
    )
    journal = simulator_admin(
        "/requests?since=" + urllib.parse.quote(since), post=False
    )
    entries = journal["requests"] if isinstance(journal, dict) else []
    tweets = hits(entries, "POST", "/2/tweets", nonce)
    check(
        "X answers 503 once and receives the resent post exactly once",
        statuses(tweets) == [503, 201],
        statuses(tweets),
    )
    check(
        "the X text carries no source link",
        bool(tweets)
        and status.get("url", "-") not in str(tweets[-1]["request"]["body"]),
    )
    check(
        "Facebook and Instagram receive the post",
        bool(hits(entries, "POST", r"/v[0-9.]+/(424242|525252)/(feed|photos)", nonce))
        and bool(hits(entries, "POST", r"/v[0-9.]+/17841400000000000/media", nonce)),
    )
    copies = [
        item
        for item in mastodon_statuses(base, source, route["account"])
        if nonce in str(item.get("content"))
        and (item.get("application") or {}).get("name") == "OpenPost"
    ]
    check(
        "OpenPost delivers one copy to the local Mastodon target",
        len(copies) == 1,
        copies,
    )
    seen.add("published")
    optout = f"cp-{secrets.token_hex(4)}"
    mastodon_post(base, source, f"Kept {optout} #{tag} #nocrosspost", None, "")
    warned = f"cp-{secrets.token_hex(4)}"
    mastodon_post(base, source, f"Spoiler {warned} #{tag}", None, "spoiler")
    drafts = wait(
        lambda: publications(token, workspace, warned),
        bool,
        POLL_SECONDS * 4,
    )
    check(
        "a status with a content warning stays a draft even on an auto route",
        bool(drafts) and all(item.get("status") == "draft" for item in drafts),
        drafts,
    )
    time.sleep(POLL_SECONDS * QUIET_POLLS)
    check(
        "a status carrying the opt-out hashtag is never forwarded",
        not publications(token, workspace, optout),
    )
    check(
        "the copy OpenPost published on Mastodon is not forwarded again",
        len(publications(token, workspace, nonce)) == len(found),
        len(publications(token, workspace, nonce)),
    )
    seen.add("drafted")
    if CROSSPOSTER:
        replayed = {"nonce": nonce, "before": str(int(status["id"]) - 1)}
        check_replay(token, workspace, route, source, replayed, len(found))
    return seen | check_failures(token, workspace, route, source)


def check_failures(token: str, workspace: str, route: dict, source: str) -> set[str]:
    base, tag = route["base_url"], route["tags"][0]
    rejected = mastodon_post(
        base,
        source,
        f"Rejected cp-{secrets.token_hex(4)} [simulate-400] #{tag}",
        None,
        "",
    )
    exhausted = mastodon_post(
        base,
        source,
        f"Exhausted cp-{secrets.token_hex(4)} [simulate-503-always] #{tag}",
        None,
        "",
    )
    urls = [str(rejected.get("url")), str(exhausted.get("url"))]
    budget = POLL_SECONDS * 6 + RETRY_SECONDS
    found, mailbox = wait(
        lambda: reports_naming(urls),
        lambda result: len(result[0]) == len(urls),
        budget,
    )
    check(
        "a provider rejection and an exhausted retry budget reach the administrator by mail",
        len(found) == len(urls),
        f"{found} of {urls}; {mailbox}",
    )
    if CROSSPOSTER:
        states = {
            state for url in urls for _, state, *_ in items(url) if state != "published"
        }
        check(
            "the rejection ends failed and the outage ends dead-lettered",
            states == {"failed", "dead_lettered"},
            states,
        )
    return {"failed", "dead_lettered"}


def check_replay(
    token: str,
    workspace: str,
    route: dict,
    source: str,
    replayed: dict[str, str],
    expected: int,
) -> None:
    nonce = replayed["nonce"]
    sql(
        "UPDATE crossposter.cursors SET cursor = %s WHERE route = %s",
        replayed["before"],
        route["name"],
    )
    time.sleep(POLL_SECONDS * QUIET_POLLS)
    check(
        "replaying the source after a cursor reset creates no second publication",
        len(publications(token, workspace, nonce)) == expected,
        len(publications(token, workspace, nonce)),
    )
    old = f"cp-{secrets.token_hex(4)}"
    holder = subprocess.Popen(
        [
            "container",
            "exec",
            CROSSPOSTER,
            "python",
            "-c",
            HELD,
            CONFIG,
            route["name"],
            "10",
        ],
        stdout=subprocess.PIPE,
    )
    holder.stdout.readline()
    mastodon_post(route["base_url"], source, f"Old {old} #{route['tags'][0]}", None, "")
    holder.wait(timeout=60)
    time.sleep(POLL_SECONDS * QUIET_POLLS)
    check(
        "re-activating a route forwards none of the posts that already exist",
        not publications(token, workspace, old)
        and bool(
            sql(
                "SELECT cursor FROM crossposter.cursors WHERE route = %s", route["name"]
            )
        ),
    )


def pixelfed_scenarios(
    token: str, workspace: str, route: dict, source: str
) -> set[str]:
    nonce = f"cp-{secrets.token_hex(4)}"
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1))
    name, mime, image = render_media("image")
    status = pixelfed_post(
        route["base_url"],
        source,
        f"Pixel {nonce} #{route['tags'][0]}",
        (name, mime, image),
    )
    check("a Pixelfed post is published", "error" not in status, status)
    found = wait(
        lambda: publications(token, workspace, nonce),
        lambda found: len(found) >= 2 and all(map(delivered, found)),
        POLL_SECONDS * 6 + 300,
    )
    check(
        "a Pixelfed post reaches Instagram and X",
        len(found) >= 2 and all(map(delivered, found)),
        [(item.get("status"), item.get("renditions")) for item in found],
    )
    journal = simulator_admin(
        "/requests?since=" + urllib.parse.quote(since), post=False
    )
    entries = journal["requests"] if isinstance(journal, dict) else []
    check(
        "Instagram receives a JPEG container for the Pixelfed image",
        bool(hits(entries, "POST", r"/v[0-9.]+/17841400000000000/media", nonce)),
    )
    return {"published"}


def peertube_scenarios(
    token: str, workspace: str, route: dict, source: str
) -> set[str]:
    nonce = f"cp-{secrets.token_hex(4)}"
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1))
    name, mime, video = render_media("video")
    uploaded = peertube_upload(
        route["base_url"],
        source,
        route["account"],
        f"Video {nonce}",
        route["tags"][0],
        (name, mime, video),
    )
    check("a PeerTube video is uploaded", "error" not in uploaded, uploaded)
    found = wait(
        lambda: publications(token, workspace, nonce),
        lambda found: bool(found) and all(map(delivered, found)),
        POLL_SECONDS * 6 + 600,
    )
    check(
        "a PeerTube video reaches YouTube",
        bool(found) and all(map(delivered, found)),
        [(item.get("status"), item.get("renditions")) for item in found],
    )
    journal = simulator_admin(
        "/requests?since=" + urllib.parse.quote(since), post=False
    )
    entries = journal["requests"] if isinstance(journal, dict) else []
    check(
        "YouTube receives one upload of the PeerTube MP4",
        len(hits(entries, "PUT", "/upload/youtube/v3/videos", "")) >= 1,
    )
    return {"published"}


SCENARIO_RUNNERS = {
    "mastodon": mastodon_scenarios,
    "pixelfed": pixelfed_scenarios,
    "peertube": peertube_scenarios,
}


def check_crossposter(token: str, workspace: str) -> None:
    tokens = json.loads(Path(SECRETS_FILE).read_text())["routes"]
    fill_sets(token, workspace)
    if CROSSPOSTER:
        check_instance()
    else:
        print("[SKIP] crossposter internals: its task runs on another swarm node")
    seen: set[str] = set()
    for route in sorted(ROUTES, key=lambda route: route["mode"] != "review"):
        seen |= SCENARIO_RUNNERS[route["platform"]](
            token, workspace, route, tokens[route["name"]]
        )
    if CROSSPOSTER:
        check_listing(seen)
