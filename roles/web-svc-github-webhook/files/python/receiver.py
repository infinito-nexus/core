#!/usr/bin/env python3
"""GitHub webhook receiver: verifies each delivery and prints one JSON line per request and per event.

Every line goes to stdout, so it reaches journald and the Wazuh agent under the container's tag.
Only an allowlist of fields is logged, never a raw payload.

Env (all required):
    WEBHOOK_SECRET        HMAC secret shared with the GitHub webhook
    WEBHOOK_PORT          port to listen on
    WEBHOOK_PATH          path GitHub posts to, e.g. /github
    WEBHOOK_MAX_BYTES     largest body accepted; a larger one is refused unread
    WEBHOOK_STATE_DB      SQLite file of the delivery IDs already accepted
    WEBHOOK_REPLAY_DAYS   days a delivery ID is remembered
    GITHUB_API_URL        GitHub REST API base URL
    GITHUB_TOKEN          read-only token for the pull request lookup; empty logs every lookup as an error
    WEBHOOK_PR_ATTEMPTS   lookups per commit before a push counts as direct
    WEBHOOK_PR_DELAY      seconds between two lookups
"""

import hashlib
import hmac
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
MAX_LOGGED_PATH = 200
MAX_COMMITS = 50
MAX_DISCARD = 16 * 1024 * 1024
WORKFLOW_PREFIX = ".github/workflows/"


def logged_path(raw_path, known):
    """Return the part of a request path that may be logged.

    Args:
        raw_path: the request target, possibly with a query string.
        known: paths the receiver serves; they are logged whole.

    Returns:
        A known path as is; any other path decoded and cut after its first segment, so a token
        further down a URL, or in the query string, never reaches the log.
    """
    path = raw_path.split("?", 1)[0]
    if path in known:
        return path
    segments = path.lstrip("/").split("/", 1)
    first = urllib.parse.unquote(segments[0])[:MAX_LOGGED_PATH]
    return f"/{first}/..." if len(segments) > 1 else f"/{first}"


def emit(record):
    with LOG_LOCK:
        sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
        sys.stdout.flush()


def flag(value):
    return "true" if value else "false"


def signature_valid(secret, body, header):
    """Check a delivery's X-Hub-Signature-256 header.

    Args:
        secret: the shared webhook secret as bytes.
        body: the raw request body.
        header: the header value, ``sha256=<hex>``, or None.

    Returns:
        True only for a well-formed header whose digest matches, compared in constant time.
    """
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), header.encode())


class DeliveryStore:
    """Delivery IDs already accepted, so a replayed delivery is refused.

    Args:
        path: SQLite file.
        keep_seconds: how long an ID is remembered.
    """

    def __init__(self, path, keep_seconds):
        self.keep_seconds = keep_seconds
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS seen (delivery TEXT PRIMARY KEY, at INTEGER NOT NULL)")
        self.db.commit()

    def first_time(self, delivery, now):
        with STATE_LOCK:
            self.db.execute("DELETE FROM seen WHERE at < ?", (int(now) - self.keep_seconds,))
            try:
                self.db.execute("INSERT INTO seen (delivery, at) VALUES (?, ?)", (delivery, int(now)))
            except sqlite3.IntegrityError:
                self.db.commit()
                return False
            self.db.commit()
            return True


def workflow_paths(payload):
    paths = set()
    for commit in payload.get("commits") or []:
        for key in ("added", "modified", "removed"):
            paths.update(p for p in commit.get(key) or [] if p.startswith(WORKFLOW_PREFIX))
    return ",".join(sorted(paths))


def default_branch(payload):
    """Return the default branch of the payload's repository, e.g. ``main``; empty when the payload has no repository."""
    return str((payload.get("repository") or {}).get("default_branch") or "")


def event_record(event, payload):
    """Reduce a webhook payload to the logged fields.

    Args:
        event: the X-GitHub-Event header.
        payload: the decoded JSON body; for an organization webhook it can come from any repository of the organization.

    Returns:
        A flat dict of strings; keys start with ``gh_`` so they never collide with Wazuh's static fields.
        Branch events carry the repository's default branch and whether the event hit it.
    """
    branch = default_branch(payload)
    default_ref = "refs/heads/" + branch if branch else ""
    record = {
        "gh_event": event,
        "gh_action": str(payload.get("action") or ""),
        "gh_repo": str((payload.get("repository") or {}).get("full_name") or ""),
        "gh_sender": str((payload.get("sender") or {}).get("login") or ""),
    }
    if event == "push":
        ref = str(payload.get("ref") or "")
        record.update(
            gh_ref=ref,
            gh_default_branch=branch,
            gh_on_default_branch=flag(bool(default_ref) and ref == default_ref),
            gh_forced=flag(payload.get("forced")),
            gh_deleted=flag(payload.get("deleted")),
            gh_created=flag(payload.get("created")),
            gh_before=str(payload.get("before") or ""),
            gh_after=str(payload.get("after") or ""),
            gh_workflow_paths=workflow_paths(payload),
        )
    elif event == "delete":
        ref = "refs/heads/" + str(payload.get("ref") or "") if payload.get("ref_type") == "branch" else ""
        record.update(
            gh_ref=ref,
            gh_default_branch=branch,
            gh_on_default_branch=flag(bool(default_ref) and ref == default_ref),
            gh_deleted="true",
        )
    elif event == "branch_protection_rule":
        record.update(gh_rule_name=str((payload.get("rule") or {}).get("name") or ""))
    elif event == "repository_ruleset":
        ruleset = payload.get("repository_ruleset") or {}
        record.update(gh_rule_name=str(ruleset.get("name") or ""), gh_enforcement=str(ruleset.get("enforcement") or ""))
    elif event == "member":
        permission = ((payload.get("changes") or {}).get("permission") or {}).get("to") or ""
        record.update(gh_member=str((payload.get("member") or {}).get("login") or ""), gh_permission=str(permission))
    elif event == "organization":
        membership = payload.get("membership") or {}
        record.update(
            gh_member=str((membership.get("user") or {}).get("login") or ""), gh_permission=str(membership.get("role") or "")
        )
    elif event == "deploy_key":
        key = payload.get("key") or {}
        record.update(gh_key_title=str(key.get("title") or ""), gh_key_read_only=flag(key.get("read_only")))
    elif event == "secret_scanning_alert":
        alert = payload.get("alert") or {}
        record.update(
            gh_alert_number=str(alert.get("number") or ""),
            gh_secret_type=str(alert.get("secret_type") or ""),
            gh_url=str(alert.get("html_url") or ""),
        )
    elif event == "dependabot_alert":
        alert = payload.get("alert") or {}
        advisory = alert.get("security_advisory") or {}
        record.update(
            gh_alert_number=str(alert.get("number") or ""),
            gh_severity=str(advisory.get("severity") or "").lower(),
            gh_package=str(((alert.get("dependency") or {}).get("package") or {}).get("name") or ""),
            gh_url=str(alert.get("html_url") or ""),
        )
    return record


def pushed_commits(payload):
    """Return the SHAs a push brought to the branch, or None when the payload lists too many to check."""
    shas = [str(c["id"]) for c in payload.get("commits") or [] if c.get("distinct", True) and c.get("id")]
    if len(shas) > MAX_COMMITS:
        return None
    if not shas and payload.get("after"):
        shas = [str(payload["after"])]
    return shas


def merged_into(api_url, token, repo, sha, branch):
    """Ask GitHub whether a commit belongs to a pull request merged into the branch.

    Args:
        api_url: GitHub REST API base URL.
        token: read-only token.
        repo: ``owner/name``.
        sha: the commit.
        branch: the repository's default branch.

    Returns:
        True when a merged pull request into the branch lists the commit.
    """
    url = f"{api_url.rstrip('/')}/repos/{repo}/commits/{sha}/pulls"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        pulls = json.load(response)
    return any(p.get("merged_at") and (p.get("base") or {}).get("ref") == branch for p in pulls)


def check_direct_push(config, delivery, repo, payload, sleep=time.sleep):
    """Log whether every commit of a push to the default branch came through a merged pull request into it.

    Args:
        config: the receiver settings (see ``load_config``).
        delivery: the delivery ID, logged for correlation.
        repo: ``owner/name``.
        payload: the push payload; its repository names the default branch.
        sleep: waits between lookups; replaced in tests.
    """
    branch = default_branch(payload)
    record = {
        "gh_kind": "direct_push",
        "gh_delivery": delivery,
        "gh_repo": repo,
        "gh_default_branch": branch,
        "gh_after": str(payload.get("after") or ""),
    }
    shas = pushed_commits(payload)
    if not config["token"]:
        emit({**record, "gh_result": "error", "gh_reason": "no token configured"})
        return
    if shas is None:
        emit({**record, "gh_result": "error", "gh_reason": f"more than {MAX_COMMITS} commits"})
        return
    unmatched = []
    for sha in shas:
        for attempt in range(config["pr_attempts"]):
            try:
                if merged_into(config["api_url"], config["token"], repo, sha, branch):
                    break
            except (urllib.error.URLError, OSError, ValueError) as error:
                emit({**record, "gh_result": "error", "gh_reason": f"lookup failed: {type(error).__name__}"})
                return
            if attempt + 1 < config["pr_attempts"]:
                sleep(config["pr_delay"])
        else:
            unmatched.append(sha)
    if unmatched:
        emit({**record, "gh_result": "no_pr", "gh_commits": ",".join(unmatched)})
    else:
        emit({**record, "gh_result": "ok", "gh_commits": ",".join(shas)})


def load_config(env):
    return {
        "secret": env["WEBHOOK_SECRET"].encode(),
        "port": int(env["WEBHOOK_PORT"]),
        "path": env["WEBHOOK_PATH"],
        "max_bytes": int(env["WEBHOOK_MAX_BYTES"]),
        "state_db": env["WEBHOOK_STATE_DB"],
        "keep_seconds": int(env["WEBHOOK_REPLAY_DAYS"]) * 86400,
        "api_url": env["GITHUB_API_URL"],
        "token": env["GITHUB_TOKEN"],
        "pr_attempts": int(env["WEBHOOK_PR_ATTEMPTS"]),
        "pr_delay": float(env["WEBHOOK_PR_DELAY"]),
    }


def make_handler(config, store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "github-webhook"
        sys_version = ""

        def log_message(self, format, *args):
            return

        def client_ip(self):
            return self.headers.get("X-Real-IP") or self.client_address[0]

        def respond(self, status, body=b""):
            path = logged_path(self.path, ("/", "/healthz", config["path"]))
            emit(
                {
                    "gh_kind": "access",
                    "gh_srcip": self.client_ip(),
                    "gh_request": f"{self.command} {path} {self.request_version}",
                    "gh_status": str(status),
                }
            )
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        # Exception: an oversized body is read and thrown away before the 413, because closing on an unread upload resets the connection and the client, or the proxy in front, never sees the status.
        def discard(self, length):
            remaining = min(length, MAX_DISCARD)
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    return
                remaining -= len(chunk)

        def reject(self, status, reason, delivery=""):
            emit({"gh_kind": "rejected", "gh_reason": reason, "gh_delivery": delivery, "gh_srcip": self.client_ip()})
            self.close_connection = True
            self.respond(status)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            self.respond(200 if path in ("/", "/healthz") else 404, b"ok\n" if path in ("/", "/healthz") else b"")

        def do_HEAD(self):
            self.respond(200 if self.path.split("?", 1)[0] in ("/", "/healthz") else 404)

        def do_POST(self):
            if self.path.split("?", 1)[0] != config["path"]:
                self.respond(404)
                return
            delivery = (self.headers.get("X-GitHub-Delivery") or "")[:64]
            try:
                length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                self.reject(411, "malformed", delivery)
                return
            if length < 0:
                self.reject(400, "malformed", delivery)
                return
            if length > config["max_bytes"]:
                self.discard(length)
                self.reject(413, "oversized", delivery)
                return
            body = self.rfile.read(length)
            signature = self.headers.get("X-Hub-Signature-256")
            if not signature:
                self.reject(401, "unsigned", delivery)
                return
            if not signature_valid(config["secret"], body, signature):
                self.reject(401, "signature", delivery)
                return
            event = self.headers.get("X-GitHub-Event") or ""
            if not delivery or not event:
                self.reject(400, "malformed", delivery)
                return
            try:
                payload = json.loads(body)
            except ValueError:
                self.reject(400, "malformed", delivery)
                return
            if not isinstance(payload, dict):
                self.reject(400, "malformed", delivery)
                return
            if not store.first_time(delivery, time.time()):
                self.reject(409, "replay", delivery)
                return
            record = event_record(event, payload)
            emit({"gh_kind": "delivery", "gh_delivery": delivery, "gh_srcip": self.client_ip(), **record})
            self.respond(202)
            if event == "push" and record["gh_on_default_branch"] == "true" and record["gh_deleted"] == "false":
                threading.Thread(
                    target=check_direct_push, args=(config, delivery, record["gh_repo"], payload), daemon=True
                ).start()

        do_PUT = do_PATCH = do_DELETE = lambda self: self.respond(405)

    return Handler


def main():
    config = load_config(os.environ)
    store = DeliveryStore(config["state_db"], config["keep_seconds"])
    server = ThreadingHTTPServer(("0.0.0.0", config["port"]), make_handler(config, store))
    server.serve_forever()


if __name__ == "__main__":
    main()
