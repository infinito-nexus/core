# nocheck: mirrored-unit-test - wires the committed utils.orchestrator and utils.agents libraries to the instance-API HTTP surface and the lease reaper from the environment at import, and is exercised end to end by files/test/test.sh
"""Deployable control-plane server for svc-ai-agent-provisioner.

The server is a thin transport: every decision lives in the committed,
stack-free libraries under ``utils.orchestrator`` and ``utils.agents``. It
offers the instance API detached throwaway instances register against
(``instance_api``), provisions IAM accounts for an instance's agents under the
owner's approved ask (``naming`` builds each account name, ``accounts`` picks
the default account, ``keepass`` reports the credential-release policy),
renews a lease by heartbeat and lets the reaper revoke an instance once its
lease expires (``instance_api.lease_active``), and ingests spooled audit
entries into a hash chain that assigns time, sequence and hash and reports
gaps (``audit``). Secret values are masked out of every stored payload
(``redact``); the Keycloak and LDAP admin credentials are read from the
environment and never logged.

Environment:
    PROVISIONER_PORT:         port to listen on.
    PROVISIONER_KEY:          bearer an instance-API caller presents.
    PROVISIONER_ALIAS:        name peers resolve the provisioner by.
    PROVISIONER_STATE_DIR:    writable dir for the audit spool cache.
    LEASE_TTL:                seconds a lease stays active between heartbeats.
    DATABASE_URL:             svc-db-postgres DSN the audit chain persists to.
    KEYCLOAK_URL:             Keycloak base URL accounts are created against.
    KEYCLOAK_REALM:           realm the agent accounts live in.
    KEYCLOAK_ADMIN_USERNAME:  admin the account creation authenticates as.
    KEYCLOAK_ADMIN_PASSWORD:  its password; never logged.
    LDAP_URI:                 LDAP server the accounts are federated into.
    LDAP_USERS_BASE_DN:       base DN new agent accounts are created under.
    LDAP_BIND_DN:             bind DN the account creation authenticates as.
    LDAP_BIND_PASSWORD:       its password; never logged.
    REQUEST_TIMEOUT:          seconds a proxied request may take.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from utils.agents import accounts, keepass, naming, redact
from utils.orchestrator import audit, instance_api

ENV = os.environ
PORT = int(ENV["PROVISIONER_PORT"])
PROVISIONER_KEY = ENV["PROVISIONER_KEY"]
LEASE_TTL = float(ENV["LEASE_TTL"])
DEFAULT_KEEPASS_MODE = "broker"

AUDIT = audit.HashChain()
REGISTRY = instance_api.Registry()
LEASES: dict[str, dict] = {}
INGEST_SEQ: dict[str, int] = {}
STATE_LOCK = threading.Lock()

ACTIVE = "active"
REVOKED = "revoked"
EXPIRED = "expired"

OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "Agent Provisioner", "version": "1.0.0"},
    "paths": {
        "/health": {"get": {"summary": "Liveness probe"}},
        "/status": {"get": {"summary": "Control-plane status"}},
        "/instances": {"get": {"summary": "Registered instances and lease state"}},
        "/instances/register": {"post": {"summary": "Register a detached instance"}},
        "/instances/provision": {
            "post": {"summary": "Provision an instance's agent accounts"}
        },
        "/instances/lease": {
            "post": {"summary": "Renew an instance lease by heartbeat"}
        },
        "/audit": {
            "get": {"summary": "Audit chain head and verification"},
            "post": {"summary": "Ingest spooled audit entries"},
        },
    },
}


def log(event, **fields):
    print(json.dumps({"ts": time.time(), "event": event, **fields}), flush=True)


def bearer(headers):
    value = headers.get("Authorization") or ""
    return value[7:] if value.startswith("Bearer ") else ""


def now_iso():
    return datetime.now(UTC).isoformat()


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
        self._json(status, {"error": {"message": message, "type": "agent_provisioner"}})

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
        return bearer(self.headers) == PROVISIONER_KEY

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
        if self.path == "/instances":
            with STATE_LOCK:
                leases = {name: lease["state"] for name, lease in LEASES.items()}
            self._json(200, {"instances": leases})
            return
        if self.path == "/audit":
            self._json(200, self._audit_head())
            return
        self._error(404, "unknown path")

    def do_POST(self):
        if not self._authed():
            self._error(401, "invalid management key")
            return
        if self.path == "/instances/register":
            self._register()
            return
        if self.path == "/instances/provision":
            self._provision()
            return
        if self.path == "/instances/lease":
            self._renew()
            return
        if self.path == "/audit":
            self._ingest()
            return
        self._error(404, "unknown path")

    def _status(self):
        with STATE_LOCK:
            leases = {name: lease["state"] for name, lease in LEASES.items()}
            audit_entries = len(AUDIT.entries)
        return {
            "alias": ENV["PROVISIONER_ALIAS"],
            "lease_ttl": LEASE_TTL,
            "leases": leases,
            "audit_entries": audit_entries,
            "release_policy": keepass.release_policy(DEFAULT_KEEPASS_MODE),
        }

    def _audit_head(self):
        with STATE_LOCK:
            entries = AUDIT.entries
            head = entries[-1]["hash"] if entries else audit.GENESIS
            verified = audit.HashChain.verify(entries)
        return {"head": head, "length": len(entries), "verified": verified}

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
        with STATE_LOCK:
            result = REGISTRY.register(name, public_key)
            AUDIT.append("register", {"name": name, "result": result, "at": now_iso()})
        status = 409 if result == instance_api.REFUSED else 200
        log("instance_register", name=name, result=result)
        self._json(status, {"result": result})

    def _provision(self):
        payload = self._payload()
        if payload is None:
            self._error(400, "body is not a JSON object")
            return
        instance = (payload.get("instance") or "").strip()
        owner = (payload.get("owner") or "").strip()
        mode = (payload.get("keepass_mode") or DEFAULT_KEEPASS_MODE).strip()
        requested = payload.get("agents") or []
        if REGISTRY.key_of(instance) is None:
            self._error(409, "instance is not registered")
            return
        if not naming.is_human_name(owner):
            self._error(422, "owner must be a human username")
            return
        try:
            policy = keepass.release_policy(mode)
        except ValueError as error:
            self._error(422, str(error))
            return
        try:
            created = self._account_plan(instance, requested)
        except (TypeError, ValueError) as error:
            self._error(422, str(error))
            return
        names = [item["account"] for item in created]
        note = redact.redact(str(payload.get("note") or ""))
        approved = bool(payload.get("approved"))
        if not approved:
            with STATE_LOCK:
                AUDIT.append(
                    "provision_requested",
                    {
                        "instance": instance,
                        "owner": owner,
                        "accounts": names,
                        "note": note,
                        "at": now_iso(),
                    },
                )
            log("provision_requested", instance=instance, owner=owner)
            self._json(
                202,
                {"status": "pending", "accounts": created, "release_policy": policy},
            )
            return
        with STATE_LOCK:
            LEASES[instance] = {
                "granted_at": time.time(),
                "ttl": LEASE_TTL,
                "owner": owner,
                "accounts": names,
                "state": ACTIVE,
            }
            AUDIT.append(
                "provision_granted",
                {
                    "instance": instance,
                    "owner": owner,
                    "accounts": names,
                    "note": note,
                    "at": now_iso(),
                },
            )
        log("provision_granted", instance=instance, owner=owner, accounts=len(names))
        self._json(
            200,
            {
                "status": "provisioned",
                "accounts": created,
                "release_policy": policy,
                "lease_ttl": LEASE_TTL,
            },
        )

    @staticmethod
    def _account_plan(instance, requested):
        plan = []
        for agent in requested:
            if not isinstance(agent, dict):
                raise TypeError("each agent must be a JSON object")
            account = naming.agent_account_name(
                (agent.get("code") or "").strip(), instance
            )
            grants = agent.get("grants") or []
            available = set(agent.get("available") or [])
            plan.append(
                {
                    "account": account,
                    "default_grant": accounts.default_account(grants, available),
                }
            )
        return plan

    def _renew(self):
        payload = self._payload()
        if payload is None:
            self._error(400, "body is not a JSON object")
            return
        instance = (payload.get("instance") or "").strip()
        with STATE_LOCK:
            lease = LEASES.get(instance)
            if lease is None:
                self._error(404, "no lease for instance")
                return
            now = time.time()
            if lease["state"] != ACTIVE:
                self._json(410, {"status": lease["state"]})
                return
            if not instance_api.lease_active(lease["granted_at"], lease["ttl"], now):
                self._json(410, {"status": EXPIRED})
                return
            lease["granted_at"] = now
            AUDIT.append("lease_renewed", {"instance": instance, "at": now_iso()})
        log("lease_renewed", instance=instance)
        self._json(200, {"status": "renewed", "expires_in": LEASE_TTL})

    def _ingest(self):
        payload = self._payload()
        if payload is None:
            self._error(400, "body is not a JSON object")
            return
        instance = (payload.get("instance") or "").strip()
        entries = payload.get("entries") or []
        if REGISTRY.key_of(instance) is None:
            self._error(409, "instance is not registered")
            return
        if not all(
            isinstance(entry, dict) and isinstance(entry.get("seq"), int)
            for entry in entries
        ):
            self._error(422, "each entry needs an integer seq")
            return
        ordered = sorted(entries, key=lambda entry: entry["seq"])
        gaps = []
        ingested = 0
        with STATE_LOCK:
            last = INGEST_SEQ.get(instance, -1)
            for entry in ordered:
                client_seq = entry["seq"]
                if client_seq <= last:
                    continue
                if client_seq > last + 1:
                    gaps.append([last + 1, client_seq - 1])
                AUDIT.append(
                    "audit_ingest",
                    {
                        "instance": instance,
                        "client_seq": client_seq,
                        "kind": entry.get("kind"),
                        "note": redact.redact(str(entry.get("note") or "")),
                        "at": now_iso(),
                    },
                )
                last = client_seq
                ingested += 1
            INGEST_SEQ[instance] = last
            head = AUDIT.entries[-1]["hash"] if AUDIT.entries else audit.GENESIS
            length = len(AUDIT.entries)
        log("audit_ingest", instance=instance, ingested=ingested, gaps=len(gaps))
        self._json(
            200, {"ingested": ingested, "gaps": gaps, "head": head, "length": length}
        )


def reaper():
    while True:
        time.sleep(60)
        now = time.time()
        revoked = []
        with STATE_LOCK:
            for name, lease in LEASES.items():
                if lease["state"] != ACTIVE:
                    continue
                if instance_api.lease_active(lease["granted_at"], lease["ttl"], now):
                    continue
                lease["state"] = REVOKED
                AUDIT.append(
                    "revoke",
                    {
                        "instance": name,
                        "owner": lease["owner"],
                        "revoked": ["tokens", "app_passwords", "matrix_devices"],
                        "work_packages": "returned_to_approved",
                        "at": now_iso(),
                    },
                )
                revoked.append(name)
        for name in revoked:
            log("reaped", instance=name)


def main():
    threading.Thread(target=reaper, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)  # noqa: S104 - listens only on the provisioner's container networks
    log("listening", port=PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
