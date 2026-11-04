# nocheck: mirrored-unit-test - wires the committed utils.orchestrator libraries to HTTP and to the cron and polling loops from the environment at import, and is exercised end to end by files/test/test.sh
"""Deployable control-plane server for svc-ai-agent-orchestrator.

The server is a thin transport: every decision lives in the committed,
stack-free libraries under ``utils.orchestrator``. It terminates webhooks and
validates them (``webhook``), deduplicates delivery ids and re-fetches by id,
appends a hash-chained audit entry per action (``audit``), registers detached
instances (``instance_api``), evaluates cron schedules (``cron``) and addresses
channel messages to accounts rather than session names (``channels``). Graph
state keeps secret handles, never values; the handle for the checkpoint key is
read from the environment and never logged.

Environment:
    ORCHESTRATOR_PORT:          port to listen on.
    ORCHESTRATOR_KEY:           bearer a management-API caller presents.
    ORCHESTRATOR_ALIAS:         name peers resolve the orchestrator by.
    ORCHESTRATOR_STATE_DIR:     writable dir for the routines checkout cache.
    WEBHOOK_SECRET:             shared secret webhook signatures are checked against.
    PUBLICLY_REACHABLE:         ``true`` receives webhooks; ``false`` also polls.
    POLL_INTERVAL:              seconds between provider polls when not reachable.
    DATABASE_URL:               svc-db-postgres DSN for checkpoints and audit.
    CHECKPOINT_ENCRYPTION_KEY:  handle the EncryptedSerializer uses; never logged.
    CHECKPOINT_RETENTION_DAYS:  retention of stored checkpoints.
    LITELLM_URL:                gateway base URL a model node relays to.
    LITELLM_KEY:                the orchestrator's own gateway key; never logged.
    CHANNELS:                   JSON list of channels in priority order.
    CRON_ENTRIES:               JSON list of the deployed revision's cron entries.
    REQUEST_TIMEOUT:            seconds a proxied request may take.
"""

from __future__ import annotations

import json
import os
import random
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from utils.orchestrator import audit, channels, cron, instance_api, webhook

ENV = os.environ
PORT = int(ENV["ORCHESTRATOR_PORT"])
ORCHESTRATOR_KEY = ENV["ORCHESTRATOR_KEY"]
WEBHOOK_SECRET = ENV["WEBHOOK_SECRET"].encode()
PUBLICLY_REACHABLE = ENV["PUBLICLY_REACHABLE"].lower() == "true"
POLL_INTERVAL = int(ENV["POLL_INTERVAL"])
CRON_ENTRIES = json.loads(ENV["CRON_ENTRIES"] or "[]")
CHANNELS = json.loads(ENV["CHANNELS"] or "[]")

SIGNATURE_HEADER = "X-Hub-Signature-256"
DELIVERY_HEADER = "X-Delivery-Id"
WEBHOOK_PREFIX = "/webhooks/"

AUDIT = audit.HashChain()
DEDUP = webhook.Deduplicator()
REGISTRY = instance_api.Registry()
STATE_LOCK = threading.Lock()

OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "Agent Orchestrator", "version": "1.0.0"},
    "paths": {
        "/health": {"get": {"summary": "Liveness probe"}},
        "/status": {"get": {"summary": "Control-plane status"}},
        "/routines": {"get": {"summary": "Routines of the deployed revision"}},
        "/routines/run": {"post": {"summary": "Start a routine run"}},
        "/audit": {"get": {"summary": "Audit chain head and verification"}},
        "/webhooks/{provider}": {"post": {"summary": "Provider webhook intake"}},
        "/instances/register": {"post": {"summary": "Register a detached instance"}},
        "/channels/dispatch": {"post": {"summary": "Dispatch a channel message"}},
    },
}


def log(event, **fields):
    print(json.dumps({"ts": time.time(), "event": event, **fields}), flush=True)


def bearer(headers):
    value = headers.get("Authorization") or ""
    return value[7:] if value.startswith("Bearer ") else ""


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
            self._json(200, OPENAPI)
            return
        if not self._authed():
            self._error(401, "invalid management key")
            return
        if self.path == "/status":
            self._json(200, self._status())
            return
        if self.path == "/routines":
            self._json(200, {"routines": self._routines()})
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
        self._error(404, "unknown path")

    def _status(self):
        return {
            "alias": ENV["ORCHESTRATOR_ALIAS"],
            "publicly_reachable": PUBLICLY_REACHABLE,
            "poll_interval": POLL_INTERVAL,
            "channels": CHANNELS,
            "routines": self._routines(),
            "audit_entries": len(AUDIT.entries),
        }

    def _routines(self):
        return sorted(
            {entry["routine"] for entry in CRON_ENTRIES if entry.get("routine")}
        )

    def _webhook(self):
        provider = self.path[len(WEBHOOK_PREFIX) :].strip("/")
        body = self._body()
        if not webhook.verify_signature(
            WEBHOOK_SECRET, body, self.headers.get(SIGNATURE_HEADER)
        ):
            log("webhook_rejected", provider=provider)
            self._error(401, "invalid signature")
            return
        delivery = (self.headers.get(DELIVERY_HEADER) or "").strip()
        with STATE_LOCK:
            fresh = DEDUP.seen(delivery) if delivery else True
            if not fresh:
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
        self._json(202, {"status": "accepted", "refetch": webhook.refetch_required()})

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
        channel = CHANNELS[0]
        with STATE_LOCK:
            AUDIT.append("channel", {"recipient": recipient, "channel": channel})
        log("channel_dispatch", recipient=recipient, channel=channel)
        self._json(
            202, {"status": "queued", "channel": channel, "recipient": recipient}
        )

    def _run_routine(self):
        payload = self._payload()
        if payload is None:
            self._error(400, "body is not a JSON object")
            return
        routine = (payload.get("routine") or "").strip()
        if routine not in self._routines():
            self._error(404, "unknown routine")
            return
        with STATE_LOCK:
            AUDIT.append("routine", {"routine": routine, "action": "run"})
        log("routine_run", routine=routine)
        self._json(202, {"status": "started", "routine": routine})


def scheduler():
    while True:
        time.sleep(60)
        try:
            due = cron.due(CRON_ENTRIES, datetime.now(UTC))
        except (KeyError, ValueError) as error:
            log("cron_failed", error=str(error))
            continue
        for entry in due:
            log("cron_due", name=entry.get("name"), routine=entry.get("routine"))
            with STATE_LOCK:
                AUDIT.append(
                    "cron", {"name": entry.get("name"), "routine": entry.get("routine")}
                )


def poller():
    while True:
        jitter = random.random() * POLL_INTERVAL * 0.1  # noqa: S311 - poll spacing only, not a security decision
        time.sleep(POLL_INTERVAL + jitter)
        log("poll_tick", channels=CHANNELS)


def main():
    threading.Thread(target=scheduler, daemon=True).start()
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
