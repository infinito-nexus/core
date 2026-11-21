import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles" / "test-e2e-playwright" / "files" / "probe_onion.sh"


class TestProbeOnion(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="probe_onion_")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.calls = self.root / "calls"

    def probe(self, curl: str) -> int:
        """Run the probe against a ``curl`` stub.

        Args:
            curl: the stub's shell body, run after it recorded its arguments.

        Returns:
            The probe's exit code.
        """
        stub = self.root / "curl"
        stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {self.calls}\n{curl}\n')
        stub.chmod(0o755)
        return subprocess.run(
            ["bash", str(SCRIPT), "127.0.0.1:9050", "x.onion", "120"],
            env={**os.environ, "PATH": f"{self.root}:{os.environ['PATH']}"},
            capture_output=True,
            check=False,
        ).returncode

    def test_any_status_below_500_answers(self):
        for code in "200", "302", "401", "499":
            with self.subTest(code=code):
                self.assertEqual(self.probe(f"printf {code}"), 0)

    def test_a_server_error_does_not_answer(self):
        for code in "500", "502", "503":
            with self.subTest(code=code):
                self.assertNotEqual(self.probe(f"printf {code}"), 0)

    def test_a_failed_connection_does_not_answer(self):
        self.assertNotEqual(self.probe("printf 000; exit 7"), 0)

    def test_one_probe_goes_through_tor_without_following_redirects(self):
        self.probe("printf 200")
        args = self.calls.read_text().splitlines()  # nocheck: cache-read
        self.assertEqual(args[args.index("--socks5-hostname") + 1], "127.0.0.1:9050")
        self.assertEqual(args[args.index("--max-time") + 1], "120")
        self.assertEqual(args[-1], "http://x.onion/")
        self.assertNotIn("-L", args)
        self.assertNotIn("--location", args)
