# nocheck: mirrored-unit-test - wires the committed utils.orchestrator libraries to HTTP and to the cron and polling loops from the environment at import, and is exercised end to end by files/test/test.sh
"""Deployable control-plane server for svc-ai-agent-orchestrator.

The server is a thin transport: every decision lives in the committed,
stack-free libraries under ``utils.orchestrator``. It terminates webhooks and
validates them (``webhook``), deduplicates delivery ids, re-fetches the named
object by id and routes the trigger it raises to the agent roles
(``dispatch``), appends a hash-chained audit entry per action (``audit``),
registers detached instances (``instance_api``), folds the cron schedules
and the measured host and lane load into one action per routine, and starts,
pauses and resumes the routines of the deployed revision under the gate and
stack locks (``scheduler``, ``probe``, ``locks``), keeps the owner's
holds and blockers across restarts (``holds``), grants the CI slot in request
order and addresses channel messages to accounts rather than session names
(``channels``). Graph state keeps secret handles, never values; the handle for
the checkpoint key is read from the environment and never logged.

Environment:
    ORCHESTRATOR_PORT:          port to listen on.
    ORCHESTRATOR_KEY:           bearer a management-API caller presents.
    ORCHESTRATOR_ALIAS:         name peers resolve the orchestrator by.
    ORCHESTRATOR_STATE_DIR:     writable dir for the holds and blockers file.
    ORCHESTRATOR_LOCK_DIR:      the machine's lock dir (gate and stack locks);
                                every routine run reads it before each step.
    WEBHOOK_SECRET:             shared secret webhook signatures are checked against.
    PUBLICLY_REACHABLE:         ``true`` receives webhooks; ``false`` also polls.
    POLL_INTERVAL:              seconds between provider polls when not reachable.
    DATABASE_URL:               svc-db-postgres DSN for checkpoints and audit.
    CHECKPOINT_ENCRYPTION_KEY:  handle the EncryptedSerializer uses; never logged.
    CHECKPOINT_RETENTION_DAYS:  retention of stored checkpoints.
    LITELLM_URL:                gateway base URL a model node relays to.
    LITELLM_KEY:                the orchestrator's own gateway key; never logged.
    CHANNELS:                   JSON list of channels in priority order.
    CRON_ENTRIES:               JSON list of the deployed revision's cron entries,
                                each tagged with the ``role`` it belongs to.
    AGENTS:                     JSON object of every role's ``triggers`` and ``owner``.
    BOARD_URL:                  origin of the OpenProject board every agent uses.
    GITHUB_TOKEN:               token the re-fetch of a GitHub event reads with;
                                absent, a webhook is audited but not acted on.
    INFINITO_INFRA_RUNNER_CONTAINER: the infra runner holding the translation
                                tools, whose own load the day rule leaves out;
                                absent, or without the ``docker`` CLI, no load is
                                measured and no load rule fires.
    REQUEST_TIMEOUT:            seconds a proxied request may take.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agents.routines import discover
from utils.orchestrator import (
    audit,
    channels,
    dispatch,
    holds,
    instance_api,
    locks,
    openapi,
    probe,
    scheduler,
    webhook,
)
from utils.orchestrator.load import PAUSE, START

ENV = os.environ
PORT = int(ENV["ORCHESTRATOR_PORT"])
ORCHESTRATOR_KEY = ENV["ORCHESTRATOR_KEY"]
WEBHOOK_SECRET = ENV["WEBHOOK_SECRET"].encode()
PUBLICLY_REACHABLE = ENV["PUBLICLY_REACHABLE"].lower() == "true"
POLL_INTERVAL = int(ENV["POLL_INTERVAL"])
REQUEST_TIMEOUT = int(ENV["REQUEST_TIMEOUT"])
CRON_ENTRIES = json.loads(ENV["CRON_ENTRIES"] or "[]")
CHANNELS = json.loads(ENV["CHANNELS"] or "[]")
AGENTS = json.loads(ENV["AGENTS"] or "{}")
TRIGGERS = {role: agent["triggers"] for role, agent in AGENTS.items()}
OWNERS = {role: agent["owner"] for role, agent in AGENTS.items()}
ROUTINE_ROLE = {
    entry["routine"]: entry.get("role") or entry["routine"] for entry in CRON_ENTRIES
}
LOCK_DIR = Path(ENV["ORCHESTRATOR_LOCK_DIR"])
BOARD_URL = ENV["BOARD_URL"]
GITHUB_TOKEN = ENV.get("GITHUB_TOKEN")
LANE_CONTAINER = ENV.get("INFINITO_INFRA_RUNNER_CONTAINER")
GITHUB_API = "https://api.github.com"
GATE_POLL_SECONDS = 5.0
HERE = Path(__file__).resolve().parent

SIGNATURE_HEADER = "X-Hub-Signature-256"
DELIVERY_HEADERS = ("X-GitHub-Delivery", "X-Gitea-Delivery", "X-Delivery-Id")
EVENT_HEADERS = ("X-GitHub-Event", "X-Gitea-Event")
WEBHOOK_PREFIX = "/webhooks/"

AUDIT = audit.HashChain()
DEDUP = webhook.Deduplicator()
REGISTRY = instance_api.Registry()
HOLDS = holds.Store(Path(ENV["ORCHESTRATOR_STATE_DIR"]) / "holds.json")
SLOTS = locks.SlotQueue()
ROUTINES = discover()
STATE_LOCK = threading.Lock()


def _spawn(argv):
    return subprocess.Popen(argv, cwd=HERE, start_new_session=True)


def _wait_gate():
    locks.wait_gate(LOCK_DIR, poll=GATE_POLL_SECONDS, sleep=time.sleep)


RUNNER = scheduler.Runner(_spawn, _wait_gate, LOCK_DIR, os.killpg)


def log(event, **fields):
    print(json.dumps({"ts": time.time(), "event": event, **fields}), flush=True)


def bearer(headers):
    value = headers.get("Authorization") or ""
    return value[7:] if value.startswith("Bearer ") else ""


def first_header(headers, names):
    for name in names:
        value = (headers.get(name) or "").strip()
        if value:
            return value
    return ""


def github_fetch(path):
    request = urllib.request.Request(  # noqa: S310 - fixed https GitHub API origin
        f"{GITHUB_API}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310 - fixed https GitHub API origin
        return json.loads(response.read())


def act(routine, role, action, source, scope=()):
    with STATE_LOCK:
        AUDIT.append(
            "routine",
            {"routine": routine, "role": role, "action": action, "source": source},
        )
    log(f"routine_{action}", routine=routine, role=role, source=source)
    if action in (START, PAUSE):
        threading.Thread(
            target=RUNNER.apply, args=(routine, role, action, tuple(scope)), daemon=True
        ).start()


def queue_message(recipient, text):
    channel = CHANNELS[0] if CHANNELS else None
    with STATE_LOCK:
        AUDIT.append("channel", {"recipient": recipient, "channel": channel})
    log("channel_dispatch", recipient=recipient, channel=channel, length=len(text))
    return channel


def start_event(event):
    roles = dispatch.route(event, TRIGGERS)
    for role in roles:
        routine = dispatch.routine_of(role, CRON_ENTRIES, ROUTINES)
        if routine is None:
            log("agent_without_routine", role=role, trigger=event.trigger)
            continue
        act(routine, role, START, event.trigger, event.scope)
    for owner, text in dispatch.notices(event, roles, OWNERS):
        if channels.is_addressable(owner):
            queue_message(owner, text)
    return roles


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, _format, *_args):
        return

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._json(
            status, {"error": {"message": message, "type": "agent_orchestrator"}}
        )

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _payload(self):
        try:
            payload = json.loads(self._body() or b"{}")
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    def _authed(self):
        return bearer(self.headers) == ORCHESTRATOR_KEY

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        if self.path == "/openapi.json":
            self._json(200, openapi.OPENAPI)
            return
        if not self._authed():
            self._error(401, "invalid management key")
            return
        if self.path == "/status":
            self._json(200, self._status())
            return
        if self.path == "/routines":
            self._json(200, {"routines": ROUTINES})
            return
        if self.path == "/audit":
            entries = AUDIT.entries
            head = entries[-1]["hash"] if entries else audit.GENESIS
            self._json(
                200,
                {
                    "head": head,
                    "length": len(entries),
                    "verified": audit.HashChain.verify(entries),
                },
            )
            return
        self._error(404, "unknown path")

    def do_POST(self):
        if self.path.startswith(WEBHOOK_PREFIX):
            self._webhook()
            return
        if not self._authed():
            self._error(401, "invalid management key")
            return
        if self.path == "/instances/register":
            self._register()
            return
        if self.path == "/channels/dispatch":
            self._dispatch()
            return
        if self.path == "/routines/run":
            self._run_routine()
            return
        if self.path in OWNER_ACTIONS:
            self._owner_action(OWNER_ACTIONS[self.path])
            return
        if self.path in ("/ci/slot", "/ci/release"):
            self._slot(self.path == "/ci/slot")
            return
        self._error(404, "unknown path")

    def _status(self):
        return {
            "alias": ENV["ORCHESTRATOR_ALIAS"],
            "publicly_reachable": PUBLICLY_REACHABLE,
            "poll_interval": POLL_INTERVAL,
            "channels": CHANNELS,
            "board": BOARD_URL,
            "routines": ROUTINES,
            "running": RUNNER.running(),
            "held": sorted(HOLDS.held()),
            "blocked": HOLDS.blockers(),
            "gate_locked": locks.held(LOCK_DIR, locks.GATE),
            "audit_entries": len(AUDIT.entries),
        }

    def _webhook(self):
        provider = self.path[len(WEBHOOK_PREFIX) :].strip("/")
        body = self._body()
        if not webhook.verify_signature(
            WEBHOOK_SECRET, body, self.headers.get(SIGNATURE_HEADER)
        ):
            log("webhook_rejected", provider=provider)
            self._error(401, "invalid signature")
            return
        delivery = first_header(self.headers, DELIVERY_HEADERS)
        if not delivery:
            log("webhook_rejected", provider=provider, reason="no delivery id")
            self._error(400, "a webhook without a delivery id cannot be deduplicated")
            return
        with STATE_LOCK:
            if not DEDUP.seen(delivery):
                log("webhook_duplicate", provider=provider, delivery=delivery)
                self._json(200, {"status": "duplicate"})
                return
            AUDIT.append(
                "webhook",
                {
                    "provider": provider,
                    "delivery": delivery,
                    "refetch": webhook.refetch_required(),
                },
            )
        log("webhook_accepted", provider=provider, delivery=delivery)
        roles = self._act_on(provider, body)
        self._json(
            202,
            {
                "status": "accepted",
                "refetch": webhook.refetch_required(),
                "roles": roles,
            },
        )

    def _act_on(self, provider, body):
        if provider != "github" or not GITHUB_TOKEN:
            return []
        try:
            payload = json.loads(body)
            event = webhook.intake(
                first_header(self.headers, EVENT_HEADERS), payload, github_fetch
            )
        except (OSError, ValueError, TypeError) as error:
            log("webhook_refetch_failed", provider=provider, error=type(error).__name__)
            return []
        return start_event(event) if event is not None else []

    def _owner_action(self, action):
        payload = self._payload()
        if payload is None:
            self._error(400, "body is not a JSON object")
            return
        routine = (payload.get("routine") or "").strip()
        if routine not in ROUTINES:
            self._error(404, "unknown routine")
            return
        reason = (payload.get("reason") or "").strip()
        if action == "hold":
            changed = HOLDS.hold(routine, reason)
        elif action == "lift":
            changed = HOLDS.lift(routine)
        elif action == "block":
            changed = HOLDS.block(routine, reason)
            if changed:
                owner = OWNERS.get(ROUTINE_ROLE.get(routine, routine))
                if owner and channels.is_addressable(owner):
                    queue_message(owner, f"{routine} is blocked: {reason}")
        else:
            changed = HOLDS.clear(routine)
        with STATE_LOCK:
            AUDIT.append("owner", {"routine": routine, "action": action})
        log(f"routine_{action}", routine=routine, changed=changed)
        self._json(200, {"routine": routine, "action": action, "changed": changed})

    def _slot(self, request):
        payload = self._payload()
        if payload is None:
            self._error(400, "body is not a JSON object")
            return
        repository = (payload.get("repository") or "").strip()
        agent = (payload.get("agent") or "").strip()
        if not repository or not channels.is_addressable(agent):
            self._error(422, "repository and an agent account are required")
            return
        if request:
            place = SLOTS.request(repository, agent)
            self._json(200, {"repository": repository, "agent": agent, "place": place})
            return
        holder = SLOTS.release(repository, agent)
        self._json(200, {"repository": repository, "holder": holder})

    def _register(self):
        payload = self._payload()
        if payload is None:
            self._error(400, "body is not a JSON object")
            return
        name = (payload.get("name") or "").strip()
        public_key = (payload.get("public_key") or "").strip()
        if not name or not public_key:
            self._error(400, "name and public_key are required")
            return
        result = REGISTRY.register(name, public_key)
        with STATE_LOCK:
            AUDIT.append("instance", {"name": name, "result": result})
        status = 409 if result == instance_api.REFUSED else 200
        self._json(status, {"result": result})

    def _dispatch(self):
        payload = self._payload()
        if payload is None:
            self._error(400, "body is not a JSON object")
            return
        recipient = (payload.get("recipient") or "").strip()
        if not channels.is_addressable(recipient):
            self._error(422, "recipient must be an agent account or human username")
            return
        if not CHANNELS:
            self._error(503, "no channel configured")
            return
        channel = queue_message(recipient, payload.get("text") or "")
        self._json(
            202, {"status": "queued", "channel": channel, "recipient": recipient}
        )

    def _run_routine(self):
        payload = self._payload()
        if payload is None:
            self._error(400, "body is not a JSON object")
            return
        routine = (payload.get("routine") or "").strip()
        role = (payload.get("role") or "").strip()
        if routine not in ROUTINES:
            self._error(404, "unknown routine")
            return
        if role not in AGENTS:
            self._error(422, "role must name an agent role")
            return
        act(routine, role, START, "management")
        self._json(202, {"status": "started", "routine": routine})


OWNER_ACTIONS = {
    "/routines/hold": "hold",
    "/routines/lift": "lift",
    "/routines/block": "block",
    "/routines/clear": "clear",
}


def cron_loop():
    stat = None
    while True:
        time.sleep(60 - time.time() % 60)
        try:
            stat, pair, accelerated = probe.lane_load(
                stat, container=LANE_CONTAINER, timeout=REQUEST_TIMEOUT, log=log
            )
            actions = scheduler.tick(
                CRON_ENTRIES,
                datetime.now(UTC).replace(second=0, microsecond=0),
                sample=pair,
                accelerated=accelerated,
                gate_locked=locks.held(LOCK_DIR, locks.GATE),
                held=HOLDS.held(),
                blocked=HOLDS.blocked(),
            )
        except (KeyError, ValueError, OSError) as error:
            log("cron_failed", error=str(error))
            continue
        for routine, action in actions.items():
            act(routine, ROUTINE_ROLE[routine], action, "cron")


def poller():
    while True:
        jitter = random.random() * POLL_INTERVAL * 0.1  # noqa: S311 - poll spacing only, not a security decision
        time.sleep(POLL_INTERVAL + jitter)
        log("poll_tick", channels=CHANNELS)


def main():
    threading.Thread(target=cron_loop, daemon=True).start()
    if not PUBLICLY_REACHABLE:
        threading.Thread(target=poller, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)  # noqa: S104 - listens only on the orchestrator's container networks
    log("listening", port=PORT, publicly_reachable=PUBLICLY_REACHABLE)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
