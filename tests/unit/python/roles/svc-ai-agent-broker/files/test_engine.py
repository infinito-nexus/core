from __future__ import annotations

import http.server
import socketserver
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/svc-ai-agent-broker/files/python"))

import engine


class RecordingEngine:
    def __init__(self, runtime):
        self.runtime = runtime
        self.calls = []

    def call(self, method, path, body=None, query=None, expect=(200,)):
        self.calls.append((method, path, body))
        if method == "GET" and path in ("/containers/json", "/services"):
            return []
        return {"Id": "abc", "Name": "/agent", "HostConfig": {"Runtime": self.runtime}}


SPEC = {
    "name": "agent-hermes-1",
    "network": "agent-hermes-1",
    "volume": "agent-hermes-1",
    "image": "hermes:1",
    "entrypoint": ["/bin/sh", "-c", 'exec "$@"', "agent"],
    "cmd": ["gateway"],
    "env": ["A=1"],
    "labels": {engine.LABEL_OWNER: "u1"},
    "data": "/opt/data",
    "user": "",
    "nano_cpus": 1,
    "memory": 2,
    "memory_reservation": 1,
    "pids": 3,
}


class TestComposeBackend(unittest.TestCase):
    def test_an_agent_on_the_host_kernel_is_stopped_and_refused(self):
        fake = RecordingEngine(runtime="runc")
        backend = engine.ComposeBackend(fake, "runsc")
        with self.assertRaises(engine.EngineError):
            backend.start({"Id": "abc"})
        self.assertIn(("POST", "/containers/abc/stop", None), fake.calls)

    def test_a_created_agent_is_pinned_to_the_runtime_and_its_own_volume(self):
        fake = RecordingEngine(runtime="runsc")
        engine.ComposeBackend(fake, "runsc").create(SPEC, "net-1")
        body = next(
            body for method, path, body in fake.calls if path == "/containers/create"
        )
        self.assertEqual(body["HostConfig"]["Runtime"], "runsc")
        self.assertEqual(
            body["HostConfig"]["Mounts"],
            [{"Type": "volume", "Source": "agent-hermes-1", "Target": "/opt/data"}],
        )
        self.assertNotIn("Privileged", body["HostConfig"])
        self.assertNotIn("Binds", body["HostConfig"])
        self.assertEqual(list(body["NetworkingConfig"]["EndpointsConfig"]), ["net-1"])


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        status, body = (200, b'{"ok": true}') if self.path == "/_ping" else (403, b"no")
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class _UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class TestUnixTransport(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "engine.sock")
        self.server = _UnixHTTPServer(self.path, _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.directory.cleanup()

    def test_a_json_answer_travels_over_the_unix_socket(self):
        self.assertEqual(
            engine.Engine(self.path, timeout=5).call("GET", "/_ping"), {"ok": True}
        )

    def test_a_refused_path_raises(self):
        with self.assertRaises(engine.EngineError):
            engine.Engine(self.path, timeout=5).call("GET", "/containers/x/exec")


class _ConnectEngine(engine.Engine):
    """Engine whose connect answers 404 for the first ``misses`` attempts."""

    def __init__(self, misses):
        self.misses = misses
        self.attempts = 0
        self.slept = 0.0

    def call(self, method, path, body=None, query=None, expect=(200,), timeout=None):
        if method == "GET":
            return {"Containers": {}}
        self.attempts += 1
        if self.attempts <= self.misses:
            raise engine.EngineError(f"POST {path} -> 404: not found", 404)
        return None


class TestConnect(unittest.TestCase):
    def setUp(self):
        self.real_sleep = engine.time.sleep
        engine.time.sleep = lambda seconds: None

    def tearDown(self):
        engine.time.sleep = self.real_sleep

    def test_a_swarm_overlay_is_joined_once_its_allocator_realizes_it(self):
        fake = _ConnectEngine(misses=3)
        fake.connect("net-1", "broker", "broker-alias")
        self.assertEqual(fake.attempts, 4)

    def test_a_network_that_stays_missing_is_not_waited_on_forever(self):
        fake = _ConnectEngine(misses=10**6)
        with self.assertRaises(engine.EngineError):
            fake.connect("net-1", "broker", "broker-alias", realize_timeout=0)
        self.assertEqual(fake.attempts, 1)

    def test_a_refusal_that_is_not_a_missing_network_is_raised_at_once(self):
        fake = _ConnectEngine(misses=0)

        def deny(method, path, body=None, query=None, expect=(200,), timeout=None):
            if method == "GET":
                return {"Containers": {}}
            raise engine.EngineError(f"POST {path} -> 403: denied", 403)

        fake.call = deny
        with self.assertRaises(engine.EngineError) as caught:
            fake.connect("net-1", "broker", "broker-alias")
        self.assertEqual(caught.exception.status, 403)


class TestSwarmBackend(unittest.TestCase):
    def test_a_service_is_placed_on_the_sandbox_nodes_and_starts_scaled_down(self):
        fake = RecordingEngine(runtime="runsc")
        engine.SwarmBackend(fake, "node.labels.kata-capable == true").create(
            SPEC, "net-1"
        )
        body = next(
            body for method, path, body in fake.calls if path == "/services/create"
        )
        self.assertEqual(
            body["TaskTemplate"]["Placement"]["Constraints"],
            ["node.labels.kata-capable == true"],
        )
        self.assertEqual(body["Mode"], {"Replicated": {"Replicas": 0}})


if __name__ == "__main__":
    unittest.main()
