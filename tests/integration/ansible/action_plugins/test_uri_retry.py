import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import PROJECT_ROOT


class TestUriRetryActionPluginIntegration(unittest.TestCase):
    def _start_flaky_server(self, fail_first_by_path: dict[str, int]):
        counters = {"total": 0, "paths": {}}

        class FlakyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path != "/" and path.endswith("/"):
                    path = path.rstrip("/")
                counters["total"] += 1
                path_count = counters["paths"].get(path, 0) + 1
                counters["paths"][path] = path_count

                if path_count <= fail_first_by_path.get(path, 0):
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b"temporary")
                    return

                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, format, *args):  # noqa: A002  override of BaseHTTPRequestHandler signature
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), FlakyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        host, port = server.server_address
        base_url = f"http://{host}:{port}"
        return server, thread, counters, base_url

    def _run_uri_retry_playbook_with_default_and_override_blocks(self):
        repo_root = PROJECT_ROOT
        server = None
        thread = None

        try:
            try:
                server, thread, counters, base_url = self._start_flaky_server(
                    fail_first_by_path={
                        "/default": 2,
                        "/override": 2,
                    }
                )
            except PermissionError as exc:
                raise unittest.SkipTest(
                    f"Cannot bind local test server in this environment: {exc}"
                ) from exc

            with tempfile.TemporaryDirectory() as tmpdir:
                playbook_path = Path(tmpdir) / "playbook.yml"
                playbook_path.write_text(
                    """
- hosts: localhost
  gather_facts: false
  tasks:
    - name: call endpoint with default uri_retry params
      uri_retry:
        url: "{{ target_url_base }}/default"
        method: GET
        status_code: 200
        timeout: 2
        return_content: true
      register: uri_result_default

    - name: call endpoint with overridden retry params
      uri_retry:
        url: "{{ target_url_base }}/override"
        method: GET
        status_code: 200
        timeout: 2
        return_content: true
      until: uri_result_override.status == 200
      retries: 3
      delay: 0
      register: uri_result_override

    - name: verify both retry blocks
      ansible.builtin.assert:
        that:
          - uri_result_default.status == 200
          - uri_result_override.status == 200
          - (uri_result_default.attempts | int) >= 2
          - (uri_result_override.attempts | int) >= 2
""".strip()
                    + "\n",
                    encoding="utf-8",
                )

                env = os.environ.copy()
                env["ANSIBLE_CONFIG"] = str(repo_root / "ansible.cfg")
                env["ANSIBLE_LOCAL_TEMP"] = "/tmp/ansible-local"

                result = subprocess.run(
                    [
                        "ansible-playbook",
                        "-i",
                        "localhost,",
                        "-c",
                        "local",
                        str(playbook_path),
                        "-e",
                        f"target_url_base={base_url}",
                    ],
                    cwd=str(repo_root),
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                return result, counters
        except unittest.SkipTest:
            raise
        except Exception as exc:
            raise self.failureException(
                "uri_retry integration test raised an exception"
            ) from exc
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=2)

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_uri_retry_runs_default_and_overridden_blocks(self):
        result, counters = (
            self._run_uri_retry_playbook_with_default_and_override_blocks()
        )

        self.assertEqual(
            result.returncode,
            0,
            msg=(
                "ansible-playbook failed\n"
                f"STDOUT:\n{result.stdout}\n\n"
                f"STDERR:\n{result.stderr}"
            ),
        )
        self.assertGreaterEqual(
            counters["paths"].get("/default", 0),
            3,
            "Expected default block to perform at least two failed attempts plus one success",
        )
        self.assertEqual(
            counters["paths"].get("/override", 0),
            3,
            "Expected overridden block to perform exactly 3 attempts with fail_first=2",
        )


if __name__ == "__main__":
    unittest.main()
