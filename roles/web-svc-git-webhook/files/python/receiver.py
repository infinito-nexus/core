"""Git webhook receiver: verifies each delivery and prints one JSON line per request and per event.

Every line goes to stdout, so it reaches journald and the Wazuh agent under the container's tag.
Only an allowlist of fields is logged, never a raw payload. Each provider posts to its own path and
is verified and reduced by its own adapter in the git package; the logged fields are shared.

Env (all required):
    WEBHOOK_PROVIDERS     JSON: path to {provider, secret, api_url, token}; a provider without a secret is not served
    WEBHOOK_PORT          port to listen on
    WEBHOOK_MAX_BYTES     largest body accepted; a larger one is refused unread
    WEBHOOK_STATE_DB      SQLite file of the delivery IDs already accepted
    WEBHOOK_REPLAY_DAYS   days a delivery ID is remembered
    WEBHOOK_API_TIMEOUT   seconds one API request of the direct-push check may take
    WEBHOOK_PR_ATTEMPTS   lookups per commit before a push counts as direct
    WEBHOOK_PR_DELAY      seconds between two lookups
"""

import ipaddress
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from git.core import CheckError, provider

LOG_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
MAX_LOGGED_PATH = 200
MAX_DISCARD = 16 * 1024 * 1024
DISCARD_CHUNK = 64 * 1024
MAX_DELIVERY_ID = 64
HEALTH_PATHS = ("/", "/healthz")
USER_AGENT = "infinito-git-webhook"


def request_path(raw_path):
    return raw_path.split("?", 1)[0]


def logged_path(raw_path, known):
    """Return the part of a request path that may be logged.

    Args:
        raw_path: the request target, possibly with a query string.
        known: paths the receiver serves; they are logged whole.

    Returns:
        A known path as is; any other path decoded and cut after its first segment, so a token
        further down a URL, or in the query string, never reaches the log.
    """
    path = request_path(raw_path)
    if path in known:
        return path
    segments = path.lstrip("/").split("/", 1)
    first = urllib.parse.unquote(segments[0])[:MAX_LOGGED_PATH]
    return f"/{first}/..." if len(segments) > 1 else f"/{first}"


def emit(record):
    with LOG_LOCK:
        sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
        sys.stdout.flush()


def default_gateway(route_table):
    """Return the IPv4 default gateway listed in /proc/net/route, None when there is none.

    Args:
        route_table: the content of /proc/net/route.
    """
    for fields in (line.split() for line in route_table.splitlines()[1:]):
        if len(fields) > 2 and fields[1] == "00000000":
            return str(ipaddress.IPv4Address(int(fields[2], 16).to_bytes(4, "little")))
    return None


def client_ip(peer, real_ip, trusted_proxy):
    """Return the client address to log: X-Real-IP only from the front proxy, otherwise the direct peer.

    Args:
        peer: the direct peer address.
        real_ip: the X-Real-IP header, None when absent.
        trusted_proxy: the address the front proxy connects from, None when unknown.
    """
    if trusted_proxy is None or peer != trusted_proxy or not real_ip:
        return peer
    try:
        return str(ipaddress.ip_address(real_ip.strip()))
    except ValueError:
        return peer


class DeliveryStore:
    """Delivery IDs already accepted, so a replayed delivery is refused.

    Args:
        path: SQLite file.
        keep_seconds: how long an ID is remembered.
    """

    def __init__(self, path, keep_seconds):
        self.keep_seconds = keep_seconds
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS seen (delivery TEXT PRIMARY KEY, at INTEGER NOT NULL)"
        )
        self.db.commit()

    def first_time(self, delivery, now):
        with STATE_LOCK:
            self.db.execute(
                "DELETE FROM seen WHERE at < ?", (int(now) - self.keep_seconds,)
            )
            try:
                self.db.execute(
                    "INSERT INTO seen (delivery, at) VALUES (?, ?)",
                    (delivery, int(now)),
                )
            except sqlite3.IntegrityError:
                self.db.commit()
                return False
            self.db.commit()
            return True


class Endpoint:
    """One provider's webhook path: its adapter, secret and the API client of its direct-push check.

    Args:
        path: the request path the provider posts to.
        settings: ``provider``, ``secret``, ``api_url`` and ``token``.
        timeout: seconds per API request.
    """

    def __init__(self, path, settings, timeout):
        self.path = path
        self.adapter = provider(settings["provider"])
        self.secret = settings["secret"]
        self.token = settings.get("token") or ""
        api_url = settings.get("api_url") or ""
        self.api = (
            self.adapter.client(api_url, self.token, timeout, USER_AGENT)
            if api_url
            else None
        )


def check_direct_push(config, endpoint, delivery, repo, payload, sleep=time.sleep):
    """Log whether every commit of a push to the default branch came through a merged pull or merge request into it.

    Args:
        config: the receiver settings (see ``load_config``).
        endpoint: the provider the push came from.
        delivery: the delivery ID, logged for correlation.
        repo: the repository path.
        payload: the push payload; it names the default branch.
        sleep: waits between lookups; replaced in tests.
    """
    adapter = endpoint.adapter
    branch = adapter.payload_default_branch(payload)
    record = {
        "gh_kind": "direct_push",
        "gh_provider": adapter.NAME,
        "gh_delivery": delivery,
        "gh_repo": repo,
        "gh_default_branch": branch,
        "gh_after": str(payload.get("after") or ""),
    }
    shas = adapter.pushed_commits(payload)
    if endpoint.api is None or not endpoint.token:
        emit({**record, "gh_result": "error", "gh_reason": "no token configured"})
        return
    if shas is None:
        emit({**record, "gh_result": "error", "gh_reason": "too many commits"})
        return
    unmatched = []
    for sha in shas:
        for attempt in range(config["pr_attempts"]):
            try:
                if adapter.merged_into(endpoint.api, repo, sha, branch):
                    break
            except (CheckError, OSError, ValueError, KeyError) as error:
                emit(
                    {
                        **record,
                        "gh_result": "error",
                        "gh_reason": f"lookup failed: {type(error).__name__}",
                    }
                )
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
    timeout = float(env["WEBHOOK_API_TIMEOUT"])
    providers = json.loads(env["WEBHOOK_PROVIDERS"])
    if not isinstance(providers, dict):
        raise ValueError(
            "WEBHOOK_PROVIDERS must be a JSON object of path to provider settings, "
            f"got a JSON {type(providers).__name__}; a value quoted once too often decodes to a str"
        )
    endpoints = {
        path: Endpoint(path, settings, timeout)
        for path, settings in providers.items()
        if settings.get("secret")
    }
    return {
        "endpoints": endpoints,
        "port": int(env["WEBHOOK_PORT"]),
        "max_bytes": int(env["WEBHOOK_MAX_BYTES"]),
        "state_db": env["WEBHOOK_STATE_DB"],
        "keep_seconds": int(env["WEBHOOK_REPLAY_DAYS"]) * 86400,
        "pr_attempts": int(env["WEBHOOK_PR_ATTEMPTS"]),
        "pr_delay": float(env["WEBHOOK_PR_DELAY"]),
    }


def report_unsupported(endpoints):
    """Log, once per start, every event field a served provider cannot deliver, so a gap is an alert and never silence.

    Args:
        endpoints: the served endpoints.
    """
    for endpoint in endpoints.values():
        for field in endpoint.adapter.UNSUPPORTED_WEBHOOK_FIELDS:
            emit(
                {
                    "gh_kind": "unsupported",
                    "gh_provider": endpoint.adapter.NAME,
                    "gh_field": field,
                }
            )


def make_handler(config, store):
    endpoints = config["endpoints"]

    class Handler(BaseHTTPRequestHandler):
        server_version = "git-webhook"
        sys_version = ""

        def log_message(self, format, *args):  # noqa: A002 - BaseHTTPRequestHandler's signature names it format
            return

        def client_ip(self):
            return client_ip(
                self.client_address[0],
                self.headers.get("X-Real-IP"),
                config["trusted_proxy"],
            )

        def respond(self, status, body=b""):
            path = logged_path(self.path, (*HEALTH_PATHS, *endpoints))
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
                chunk = self.rfile.read(min(remaining, DISCARD_CHUNK))
                if not chunk:
                    return
                remaining -= len(chunk)

        def reject(self, endpoint, status, reason, delivery=""):
            emit(
                {
                    "gh_kind": "rejected",
                    "gh_provider": endpoint.adapter.NAME,
                    "gh_reason": reason,
                    "gh_delivery": delivery,
                    "gh_srcip": self.client_ip(),
                }
            )
            self.close_connection = True
            self.respond(status)

        def do_GET(self):
            healthy = request_path(self.path) in HEALTH_PATHS
            self.respond(200 if healthy else 404, b"ok\n" if healthy else b"")

        def do_HEAD(self):
            self.respond(200 if request_path(self.path) in HEALTH_PATHS else 404)

        def do_POST(self):
            endpoint = endpoints.get(request_path(self.path))
            if endpoint is None:
                self.respond(404)
                return
            adapter = endpoint.adapter
            delivery = adapter.webhook_delivery(self.headers)[:MAX_DELIVERY_ID]
            try:
                length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                self.reject(endpoint, 411, "malformed", delivery)
                return
            if length < 0:
                self.reject(endpoint, 400, "malformed", delivery)
                return
            if length > config["max_bytes"]:
                self.discard(length)
                self.reject(endpoint, 413, "oversized", delivery)
                return
            body = self.rfile.read(length)
            failure = adapter.webhook_verify(
                self.headers, body, endpoint.secret, time.time()
            )
            if failure == "replay":
                self.reject(endpoint, 409, failure, delivery)
                return
            if failure:
                self.reject(endpoint, 401, failure, delivery)
                return
            try:
                payload = json.loads(body)
            except ValueError:
                self.reject(endpoint, 400, "malformed", delivery)
                return
            if not isinstance(payload, dict):
                self.reject(endpoint, 400, "malformed", delivery)
                return
            event = adapter.webhook_event(self.headers, payload)
            if not delivery or not event:
                self.reject(endpoint, 400, "malformed", delivery)
                return
            if not store.first_time(f"{adapter.NAME}:{delivery}", time.time()):
                self.reject(endpoint, 409, "replay", delivery)
                return
            record = adapter.webhook_record(event, payload)
            emit(
                {
                    "gh_kind": "delivery",
                    "gh_delivery": delivery,
                    "gh_srcip": self.client_ip(),
                    **record,
                }
            )
            self.respond(202)
            if (
                event == "push"
                and record["gh_on_default_branch"] == "true"
                and record["gh_deleted"] == "false"
            ):
                threading.Thread(
                    target=check_direct_push,
                    args=(config, endpoint, delivery, record["gh_repo"], payload),
                    daemon=True,
                ).start()

        do_PUT = do_PATCH = do_DELETE = lambda self: self.respond(405)  # noqa: N815 - http.server dispatches on these exact method names

    return Handler


def main():
    # Exception: the front proxy reaches the container through its published port, so its connections arrive from the network gateway; any other peer's X-Real-IP is ignored.
    config = {
        **load_config(os.environ),
        "trusted_proxy": default_gateway(
            Path("/proc/net/route").read_text(encoding="ascii")
        ),
    }
    store = DeliveryStore(config["state_db"], config["keep_seconds"])
    report_unsupported(config["endpoints"])
    bind = "0.0.0.0"  # noqa: S104 - binds inside its own container network namespace; the compose port mapping decides what the host exposes
    server = ThreadingHTTPServer((bind, config["port"]), make_handler(config, store))
    server.serve_forever()


if __name__ == "__main__":
    main()
