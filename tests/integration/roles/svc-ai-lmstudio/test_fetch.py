from __future__ import annotations

import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests.integration.roles import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles/svc-ai-lmstudio/tasks"
FETCH = TASKS / "utils/fetch.yml"
BLOB = bytes(range(256)) * 1024
REPO = "lmstudio-community/Probe-GGUF"
FILE = "Probe-Q4_K_M.gguf"

PLAYBOOK = """
- hosts: localhost
  gather_facts: false
  tasks:
    - ansible.builtin.include_tasks: "{{ fetch }}"
"""


def _serve(resets: int, corrupt: bool) -> tuple[ThreadingHTTPServer, dict]:
    """
    Args:
        resets: how many transfers the source cuts off halfway with a TCP reset.
        corrupt: whether every body the source sends differs from BLOB.

    Returns:
        The running source and its request counter.
    """
    state = {"requests": 0}

    class Source(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state["requests"] += 1
            body = bytes(reversed(BLOB)) if corrupt else BLOB
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if state["requests"] <= resets:
                self.wfile.write(body[: len(body) // 2])
                self.wfile.flush()
                self.connection.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
                self.connection.close()
                self.close_connection = True
                return
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Source)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


def _fetch(
    resets: int, corrupt: bool, floor: int, stale: bool
) -> tuple[int, str, bytes, int, float, list[str]]:
    """
    Args:
        resets: how many transfers the source cuts off halfway.
        corrupt: whether the source only ever sends other bytes than BLOB.
        floor: the download budget floor in seconds.
        stale: whether an interrupted earlier fetch left a partial in staging.

    Returns:
        The play's exit code, its output, the stored model (b"" when absent),
        the requests the source answered, the play's wall time and what
        staging holds afterwards.
    """
    server, state = _serve(resets, corrupt)
    try:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            store = root / "store"
            staging = store / ".staging"
            stored = store / REPO / FILE
            if stale:
                staging.mkdir(parents=True)
                (staging / "tmpinterrupted").write_bytes(BLOB[:1024])
            host, port = server.server_address[:2]
            variables = root / "vars.json"
            variables.write_text(
                json.dumps(
                    {
                        "fetch": str(FETCH),
                        "ansible_python_interpreter": sys.executable,
                        "lmstudio_fetch_store": str(store),
                        "lmstudio_fetch_staging": str(staging),
                        "lmstudio_fetch_node": "localhost",
                        "LMSTUDIO_PRELOAD_FLOOR_SECONDS": floor,
                        "LMSTUDIO_PRELOAD_MIN_BYTES_PER_SECOND": 1_000_000,
                        "LMSTUDIO_PRELOAD_LARGEST_BYTES": len(BLOB),
                        "LMSTUDIO_PRELOAD_MODELS": [
                            {
                                "repo": REPO,
                                "file": FILE,
                                "url": f"http://{host}:{port}/{FILE}",
                                "sha256": hashlib.sha256(BLOB).hexdigest(),
                                "bytes": len(BLOB),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            playbook = root / "playbook.yml"
            playbook.write_text(PLAYBOOK, encoding="utf-8")
            env = {
                **os.environ,
                "ANSIBLE_CONFIG": str(PROJECT_ROOT / "ansible.cfg"),
                "ANSIBLE_HOME": str(root / "ansible-home"),
                "ANSIBLE_LOCAL_TEMP": str(root / "ansible-local"),
                "ANSIBLE_REMOTE_TEMP": str(root / "ansible-remote"),
            }
            began = time.monotonic()
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ansible.cli.playbook",
                    "-i",
                    "localhost,",
                    "-c",
                    "local",
                    str(playbook),
                    "-e",
                    f"@{variables}",
                ],
                cwd=str(PROJECT_ROOT),
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
            elapsed = time.monotonic() - began
            body = b""
            if stored.exists():
                body = stored.read_bytes()  # nocheck: cache-read  the play wrote it
            return (
                result.returncode,
                result.stdout + result.stderr,
                body,
                state["requests"],
                elapsed,
                sorted(os.listdir(staging)) if staging.exists() else [],
            )
    finally:
        server.shutdown()
        server.server_close()


def _includes_fetch(tasks: list) -> bool:
    """
    Args:
        tasks: a parsed task list.

    Returns:
        Whether any task in it, nested blocks included, includes utils/fetch.yml.
    """
    for task in tasks or []:
        include = task.get("ansible.builtin.include_tasks")
        target = include.get("file") if isinstance(include, dict) else include
        if target == "utils/fetch.yml":
            return True
        if any(_includes_fetch(task.get(key)) for key in ("block", "rescue")):
            return True
    return False


class TestFetch(unittest.TestCase):
    def test_a_reset_transfer_costs_a_retry_not_the_deploy(self) -> None:
        rc, output, body, requests, _elapsed, _staged = _fetch(1, False, 60, False)
        self.assertEqual(rc, 0, output[-3000:])
        self.assertEqual(body, BLOB)
        self.assertEqual(requests, 2)

    def test_an_interrupted_fetch_leaves_no_partial_behind(self) -> None:
        rc, output, body, _requests, _elapsed, staged = _fetch(0, False, 60, True)
        self.assertEqual(rc, 0, output[-3000:])
        self.assertEqual(body, BLOB)
        self.assertEqual(staged, [])

    def test_a_source_that_never_verifies_fails_closed_inside_the_budget(self) -> None:
        rc, output, body, requests, elapsed, _staged = _fetch(0, True, 4, False)
        self.assertNotEqual(rc, 0, output[-3000:])
        self.assertIn("Timed out after 4 second(s)", output, output[-3000:])
        self.assertEqual(body, b"")
        self.assertGreater(requests, 0)
        self.assertLess(elapsed, 4 + 30)

    def test_the_swarm_seed_and_the_node_preload_share_one_fetch(self) -> None:
        for caller in ("00_core.yml", "utils/preload/node.yml"):
            with self.subTest(caller=caller):
                self.assertTrue(
                    _includes_fetch(
                        load_yaml_any(str(TASKS / caller), default_if_missing=[])
                    )
                )


if __name__ == "__main__":
    unittest.main()
