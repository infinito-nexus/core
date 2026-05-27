import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT


class TestGetUrlRetryActionPluginIntegration(unittest.TestCase):
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
                self.wfile.write(path.encode("utf-8"))

            def log_message(self, format, *args):  # noqa: A002  override of BaseHTTPRequestHandler signature
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), FlakyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        host, port = server.server_address
        base_url = f"http://{host}:{port}"
        return server, thread, counters, base_url

    def _run_get_url_retry_playbook_with_default_and_override_blocks(self):
        repo_root = PROJECT_ROOT
        server = None
        thread = None

        try:
            try:
                server, thread, counters, base_url = self._start_flaky_server(
                    fail_first_by_path={
                        "/default": 2,
                        "/override": 3,
                    }
                )
            except PermissionError as exc:
                raise unittest.SkipTest(
                    f"Cannot bind local test server in this environment: {exc}"
                ) from exc

            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)
                default_dest = tmpdir_path / "default.txt"
                override_dest = tmpdir_path / "override.txt"
                playbook_path = tmpdir_path / "playbook.yml"
                playbook_path.write_text(
                    """
- hosts: localhost
  gather_facts: false
  tasks:
    - name: download with default get_url_retry params
      get_url_retry:
        url: "{{ target_url_base }}/default"
        dest: "{{ default_dest }}"
        mode: "0644"
        timeout: 2
      register: download_default

    - name: download with overridden retry params
      get_url_retry:
        url: "{{ target_url_base }}/override"
        dest: "{{ override_dest }}"
        mode: "0644"
        timeout: 2
      retries: 0
      delay: 0
      ignore_errors: true
      register: download_override

    - name: verify both download blocks
      ansible.builtin.assert:
        that:
          - download_default is succeeded
          - download_override is failed
          - (download_default.attempts | int) >= 3
          - (download_override.attempts | int) == 1
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
                        "-e",
                        f"default_dest={default_dest}",
                        "-e",
                        f"override_dest={override_dest}",
                    ],
                    cwd=str(repo_root),
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                default_content = read_text(str(default_dest))
                override_exists = override_dest.exists()

                return result, counters, default_content, override_exists
        except unittest.SkipTest:
            raise
        except Exception as exc:
            raise self.failureException(
                "get_url_retry integration test raised an exception"
            ) from exc
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=2)

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_get_url_retry_runs_default_and_overridden_blocks(self):
        result, counters, default_content, override_exists = (
            self._run_get_url_retry_playbook_with_default_and_override_blocks()
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
        self.assertGreaterEqual(
            counters["paths"].get("/override", 0),
            1,
            "Expected at least one request for overridden block",
        )
        self.assertLessEqual(
            counters["paths"].get("/override", 0),
            3,
            "Expected only a small number of requests for one plugin attempt with retries=0",
        )
        self.assertEqual(default_content, "/default")
        self.assertFalse(
            override_exists,
            "Override destination file should not exist after expected failed download",
        )


if __name__ == "__main__":
    unittest.main()
