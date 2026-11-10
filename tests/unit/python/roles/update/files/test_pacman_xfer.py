import http.server
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

SCRIPT = PROJECT_ROOT / "roles/update/files/shell/pacman_xfer.sh"
OLD_XFERCOMMAND = (
    "curl -L -C - -f --connect-timeout 5 --retry 3 --retry-all-errors "
    "--retry-delay 2 -o %o %u"
)
BODY = "0123456789abcdef" * 65536
DATA = BODY.encode()
PATH = "/core/core.db"
SLEEP_STUB = '#!/bin/sh\necho "$@" >> "${SLEEP_LOG}"\n'
CURL_STUB = "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"${CURL_ARGV}\"\nprintf '200 '\n"


class _Mirror(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, plan):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.plan = plan
        self.hits = 0
        self.ranges = []
        self.lock = threading.Lock()
        self.retried = threading.Event()

    def handle_error(self, request, client_address):
        pass


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        mirror = self.server
        with mirror.lock:
            mirror.hits += 1
            hit = mirror.hits
            mirror.ranges.append(self.headers.get("Range"))
        if hit > 1:
            mirror.retried.set()
        step = mirror.plan[min(hit, len(mirror.plan)) - 1]
        if isinstance(step, str):
            getattr(self, f"_{step}")()
        elif isinstance(step, tuple):
            self._status(*step)
        else:
            self._status(step, None)

    def _status(self, code, retry_after):
        self.send_response(code)
        if retry_after is not None:
            self.send_header("Retry-After", retry_after)
        self.send_header("Content-Length", "9")
        self.end_headers()
        self.wfile.write(b"error\n\n\n\n")

    def _reset(self):
        self.close_connection = True
        self.connection.setsockopt(
            socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00"
        )
        os.close(self.connection.detach())

    def _send(self, cut):
        offset = int((self.headers.get("Range") or "bytes=0-")[6:-1])
        self.send_response(206 if offset else 200)
        if offset:
            self.send_header(
                "Content-Range", f"bytes {offset}-{len(DATA) - 1}/{len(DATA)}"
            )
        self.send_header("Content-Length", str(len(DATA) - offset))
        self.end_headers()
        rest = DATA[offset:]
        if not cut:
            self.wfile.write(rest)
            return
        self.wfile.write(rest[: len(rest) // 2])
        self.wfile.flush()
        self._reset()

    def _ok(self):
        self._send(cut=False)

    def _cut(self):
        self._send(cut=True)


class TestPacmanXfer(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.stub("sleep", SLEEP_STUB)
        self.sleep_log = self.root / "sleeps"
        self.output = self.root / "core.db.part"
        self.plain_env = dict(os.environ)
        self.plain_env["no_proxy"] = self.plain_env["NO_PROXY"] = "127.0.0.1"
        self.env = dict(self.plain_env)
        self.env["PATH"] = f"{self.bin_dir}{os.pathsep}{self.env['PATH']}"
        self.env["SLEEP_LOG"] = str(self.sleep_log)

    def stub(self, name, body):
        """Put an executable stub first on the wrapper's PATH.

        Args:
            name: the command the stub replaces.
            body: the stub's shell script.
        """
        stub = self.bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)

    def serve(self, plan):
        """Start a mirror on 127.0.0.1 that answers PATH by plan.

        Args:
            plan: one step per request, the last one repeats: "ok", "cut"
                (half the body, then a reset) or "reset" (before any
                response), an HTTP status code, or a (status, Retry-After)
                tuple.

        Returns:
            The running mirror and the URL of PATH on it.
        """
        mirror = _Mirror(plan)
        threading.Thread(
            target=mirror.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()
        self.addCleanup(mirror.server_close)
        self.addCleanup(mirror.shutdown)
        return mirror, f"http://127.0.0.1:{mirror.server_address[1]}{PATH}"

    def xfer(self, plan, partial=None, env=None):
        """Run the wrapper the way pacman does, with %o and %u filled in.

        Args:
            plan: the mirror's steps, see serve().
            partial: text the output file holds before the run, or None
                when it does not exist.
            env: environment for the run, or None for the one with the
                sleep stub.

        Returns:
            Tuple of exit code, the mirror, and the output file's text after
            the run (None when it does not exist).
        """
        mirror, url = self.serve(plan)
        if partial is not None:
            self.output.write_text(partial)
        done = subprocess.run(
            ["bash", str(SCRIPT), str(self.output), url],
            env=self.env if env is None else env,
            capture_output=True,
            timeout=60,
            check=False,
        )
        after = read_text(str(self.output)) if self.output.exists() else None
        return done.returncode, mirror, after

    def sleeps(self):
        """Return the arguments of every sleep the wrapper ran, in order."""
        if not self.sleep_log.exists():
            return []
        return read_text(str(self.sleep_log)).split()

    def assert_retried_once(self, step):
        """Assert that one failing answer is retried and the retry succeeds.

        Args:
            step: the mirror's first answer, see serve().
        """
        code, mirror, after = self.xfer([step, "ok"])
        self.assertEqual(code, 0)
        self.assertEqual(mirror.hits, 2)
        self.assertEqual(after, BODY)

    def test_old_xfercommand_retries_a_404(self):
        mirror, url = self.serve([404])
        argv = [
            arg.replace("%o", str(self.output)).replace("%u", url)
            for arg in OLD_XFERCOMMAND.split()
        ]
        proc = subprocess.Popen(
            argv, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            retried = mirror.retried.wait(timeout=30)
        finally:
            proc.kill()
            proc.wait()
        self.assertTrue(retried)

    def test_a_404_fails_at_once_without_a_file(self):
        code, mirror, after = self.xfer([404])
        self.assertEqual(code, 22)
        self.assertEqual(mirror.hits, 1)
        self.assertIsNone(after)

    def test_a_410_fails_at_once(self):
        code, mirror, _ = self.xfer([410])
        self.assertEqual(code, 22)
        self.assertEqual(mirror.hits, 1)

    def test_a_404_leaves_a_partial_download_untouched(self):
        code, mirror, after = self.xfer([404], partial=BODY[:1000])
        self.assertEqual(code, 22)
        self.assertEqual(mirror.hits, 1)
        self.assertEqual(after, BODY[:1000])

    def test_a_403_is_retried(self):
        self.assert_retried_once(403)

    def test_a_408_is_retried(self):
        self.assert_retried_once(408)

    def test_a_421_is_retried(self):
        self.assert_retried_once(421)

    def test_a_429_is_retried(self):
        self.assert_retried_once(429)

    def test_a_503_is_retried(self):
        self.assert_retried_once(503)

    def test_a_reset_connection_is_retried(self):
        self.assert_retried_once("reset")

    def test_a_cut_transfer_drops_its_bytes_before_the_retry(self):
        code, mirror, after = self.xfer(["cut", "ok"])
        self.assertEqual(code, 0)
        self.assertEqual(mirror.ranges, [None, None])
        self.assertEqual(after, BODY)

    def test_a_cut_resume_retries_from_the_original_offset(self):
        code, mirror, after = self.xfer(["cut", "ok"], partial=BODY[:1000])
        self.assertEqual(code, 0)
        self.assertEqual(mirror.ranges, ["bytes=1000-", "bytes=1000-"])
        self.assertEqual(after, BODY)

    def test_a_partial_download_resumes(self):
        code, mirror, after = self.xfer(["ok"], partial=BODY[:1000])
        self.assertEqual(code, 0)
        self.assertEqual(mirror.ranges, ["bytes=1000-"])
        self.assertEqual(after, BODY)

    def test_a_lasting_failure_exits_non_zero_after_three_retries(self):
        code, mirror, _ = self.xfer([503])
        self.assertEqual(code, 22)
        self.assertEqual(mirror.hits, 4)
        self.assertEqual(self.sleeps(), ["2", "2", "2"])

    def test_a_retry_after_waits_that_long(self):
        start = time.monotonic()
        code, mirror, _ = self.xfer([(429, "4"), "ok"], env=self.plain_env)
        waited = time.monotonic() - start
        self.assertEqual(code, 0)
        self.assertEqual(mirror.hits, 2)
        self.assertGreaterEqual(waited, 4)
        self.assertLess(waited, 15)

    def test_a_retry_after_on_503_sets_the_delay(self):
        self.xfer([(503, "4"), "ok"])
        self.assertEqual(self.sleeps(), ["4"])

    def test_a_retry_after_is_capped_at_30_seconds(self):
        self.xfer([(503, "120"), "ok"])
        self.assertEqual(self.sleeps(), ["30"])

    def test_a_retry_after_below_2_seconds_keeps_2(self):
        self.xfer([(429, "0"), "ok"])
        self.assertEqual(self.sleeps(), ["2"])

    def test_a_retry_after_that_is_no_seconds_count_keeps_2(self):
        values = ("Wed, 21 Oct 2026 07:28:00 GMT", "soon", "-5", "4.5")
        for index, value in enumerate(values):
            with self.subTest(value=value):
                self.sleep_log = self.root / f"sleeps-{index}"
                self.env["SLEEP_LOG"] = str(self.sleep_log)
                self.output = self.root / f"core-{index}.db.part"
                self.xfer([(503, value), "ok"])
                self.assertEqual(self.sleeps(), ["2"])

    def test_a_retry_after_on_another_status_is_ignored(self):
        self.xfer([(500, "4"), "ok"])
        self.assertEqual(self.sleeps(), ["2"])

    def test_curl_gets_a_connect_timeout(self):
        argv_log = self.root / "curl-argv"
        self.stub("curl", CURL_STUB)
        self.env["CURL_ARGV"] = str(argv_log)
        code, _, _ = self.xfer(["ok"])
        argv = read_text(str(argv_log)).splitlines()
        self.assertEqual(code, 0)
        self.assertIn("--connect-timeout", argv)
        self.assertEqual(argv[argv.index("--connect-timeout") + 1], "5")


if __name__ == "__main__":
    unittest.main()
