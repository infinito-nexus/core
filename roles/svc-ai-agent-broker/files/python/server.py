# nocheck: mirrored-unit-test - builds its engine, agents and access clients from the environment at import and is exercised end to end by files/test/test.sh
"""
Environment:
    BROKER_PORT:              port to listen on.
    BROKER_KEY:               bearer Open WebUI presents.
    BROKER_ALIAS:             name agents resolve the broker by.
    ENGINE_SOCKET:            filtered engine socket of the socket proxy.
    ENGINE_MODE:              ``compose`` or ``swarm``.
    AGENT_RUNTIME:            OCI runtime of compose agents.
    AGENT_CONSTRAINT:         placement constraint of swarm agents.
    LITELLM_URL:              gateway base URL.
    LITELLM_KEY:              the broker's own gateway key.
    AGENT_MODEL:              model alias agents are configured with.
    AGENT_CONTEXT:            context window of that model in tokens; empty leaves it to the agent.
    AGENT_PLATFORMS:          JSON platform name -> spec.
    KEYCLOAK_URL:             Keycloak base URL.
    KEYCLOAK_REALM:           realm of the platform users.
    KEYCLOAK_ADMIN_USERNAME:  master-realm administrator.
    KEYCLOAK_ADMIN_PASSWORD:  its password.
    ACCESS_CACHE_SECONDS:     reuse window of a membership answer.
    IDLE_STOP:                ``true`` stops idle agents.
    IDLE_MINUTES:             idle time before a stop.
    MAX_RUNNING:              bound on concurrently running agents.
    START_TIMEOUT:            seconds an agent gets to become healthy.
    REQUEST_TIMEOUT:          seconds a proxied request may take.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from access import AccessError, Keycloak
from agents import Agents, CapacityError
from engine import ComposeBackend, Engine, EngineError, SwarmBackend

ENV = os.environ
PORT = int(ENV["BROKER_PORT"])
BROKER_KEY = ENV["BROKER_KEY"]
LITELLM = urllib.parse.urlsplit(ENV["LITELLM_URL"])
LITELLM_KEY = ENV["LITELLM_KEY"]
REQUEST_TIMEOUT = float(ENV["REQUEST_TIMEOUT"])
PLATFORMS = json.loads(ENV["AGENT_PLATFORMS"])
USER_ID_HEADER = "X-OpenWebUI-User-Id"
USER_EMAIL_HEADER = "X-OpenWebUI-User-Email"
HOP_BY_HOP = {"connection", "transfer-encoding", "keep-alive", "content-length"}

ENGINE = Engine(ENV["ENGINE_SOCKET"], timeout=120)
BACKEND = (
    SwarmBackend(ENGINE, ENV["AGENT_CONSTRAINT"])
    if ENV["ENGINE_MODE"] == "swarm"
    else ComposeBackend(ENGINE, ENV["AGENT_RUNTIME"])
)
AGENTS = Agents(
    backend=BACKEND,
    engine=ENGINE,
    platforms=PLATFORMS,
    self_container=socket.gethostname(),
    broker_alias=ENV["BROKER_ALIAS"],
    relay_url=f"http://{ENV['BROKER_ALIAS']}:{PORT}/llm/v1",
    model=ENV["AGENT_MODEL"],
    context=int(ENV["AGENT_CONTEXT"] or 0),
    idle_stop=ENV["IDLE_STOP"].lower() == "true",
    idle_seconds=int(ENV["IDLE_MINUTES"]) * 60,
    max_running=int(ENV["MAX_RUNNING"]),
    start_timeout=int(ENV["START_TIMEOUT"]),
)
ACCESS = Keycloak(
    ENV["KEYCLOAK_URL"],
    ENV["KEYCLOAK_REALM"],
    ENV["KEYCLOAK_ADMIN_USERNAME"],
    ENV["KEYCLOAK_ADMIN_PASSWORD"],
    cache_seconds=int(ENV["ACCESS_CACHE_SECONDS"]),
    timeout=15,
)


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
        self._json(status, {"error": {"message": message, "type": "agent_broker"}})

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _proxy(self, host, port, path, body, headers):
        connection = http.client.HTTPConnection(host, port, timeout=REQUEST_TIMEOUT)
        try:
            connection.request(self.command, path, body=body, headers=headers)
            upstream = connection.getresponse()
            self.send_response(upstream.status)
            for name, value in upstream.getheaders():
                if name.lower() not in HOP_BY_HOP:
                    self.send_header(name, value)
            self.end_headers()
            while chunk := upstream.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
            return upstream.status
        finally:
            connection.close()

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        if self.path.startswith("/llm/"):
            self._relay()
            return
        if bearer(self.headers) != BROKER_KEY:
            self._error(401, "invalid broker key")
            return
        if self.path == "/v1/models":
            self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": name, "object": "model", "owned_by": "agent-broker"}
                        for name in sorted(PLATFORMS)
                    ],
                },
            )
            return
        self._error(404, "unknown path")

    def do_POST(self):
        if self.path.startswith("/llm/"):
            self._relay()
            return
        if bearer(self.headers) != BROKER_KEY:
            self._error(401, "invalid broker key")
            return
        if self.path != "/v1/chat/completions":
            self._error(404, "unknown path")
            return
        self._chat()

    def _chat(self):
        owner = (self.headers.get(USER_ID_HEADER) or "").strip()
        email = (self.headers.get(USER_EMAIL_HEADER) or "").strip()
        if not owner:
            self._error(401, f"{USER_ID_HEADER} missing")
            return
        try:
            payload = json.loads(self._body() or b"{}")
        except ValueError:
            self._error(400, "body is not JSON")
            return
        platform = payload.get("model")
        if platform not in PLATFORMS:
            self._error(404, f"unknown agent platform '{platform}'")
            return
        try:
            allowed = ACCESS.allows(email, PLATFORMS[platform]["group"])
        except AccessError as error:
            log("access_unavailable", platform=platform, error=str(error))
            self._error(503, "access check unavailable")
            return
        if not allowed:
            log("refused", platform=platform, owner=owner)
            AGENTS.stop_owner(platform, owner)
            self._error(403, f"not entitled to the {platform} agent")
            return
        try:
            address, key = AGENTS.ensure(platform, owner)
        except CapacityError as error:
            self._error(503, str(error))
            return
        except (EngineError, TimeoutError) as error:
            log("agent_failed", platform=platform, owner=owner, error=str(error))
            self._error(502, f"agent could not be started: {error}")
            return
        payload["model"] = AGENTS.agent_model(platform, address, key)
        payload["user"] = owner
        target = urllib.parse.urlsplit(address)
        log("forward", platform=platform, owner=owner)
        self._proxy(
            target.hostname,
            target.port,
            "/v1/chat/completions",
            json.dumps(payload).encode(),
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )

    def _relay(self):
        entry = AGENTS.owner_of_key(bearer(self.headers))
        if entry is None:
            self._error(401, "unknown agent key")
            return
        owner, platform = entry
        body = self._body()
        if body and self.command == "POST":
            try:
                payload = json.loads(body)
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                payload["user"] = owner
                body = json.dumps(payload).encode()
        headers = {
            "Authorization": f"Bearer {LITELLM_KEY}",
            "Content-Type": self.headers.get("Content-Type") or "application/json",
        }
        path = self.path[len("/llm") :]
        status = self._proxy(
            LITELLM.hostname, LITELLM.port, path, body or None, headers
        )
        log("relay", owner=owner, platform=platform, path=path, status=status)


def reaper():
    while True:
        time.sleep(60)
        try:
            AGENTS.reap()
        except (EngineError, OSError) as error:
            log("reap_failed", error=str(error))


def main():
    threading.Thread(target=reaper, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)  # noqa: S104 - listens only on the broker's container networks
    log("listening", port=PORT, mode=ENV["ENGINE_MODE"])
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
