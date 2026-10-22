import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/web-app-openproject/files/shell/await_migrations.sh"

BUNDLE_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"${STUB_DIR}/calls"
cat "${STUB_DIR}/status"
exit "${STUB_RC}"
"""

HEADER = (
    "\ndatabase: openproject\n\n"
    " Status   Migration ID    Migration Name\n" + "-" * 50 + "\n"
)
ALL_UP = HEADER + "   up     1000016         Aggregated migrations\n"
ONE_DOWN = ALL_UP + "  down    20261001000000  Add announcement flags\n"


class TestAwaitMigrations(unittest.TestCase):
    def run_gate(self, status, rc=0):
        """Run the gate against a stubbed `bundle` with a 2 s deadline.

        Args:
            status: what the stubbed `rails db:migrate:status` prints.
            rc: exit code of the stubbed `bundle`.

        Returns:
            Tuple of the gate's stdout plus stderr and the recorded `bundle` calls.
        """
        with tempfile.TemporaryDirectory() as tmp:
            stub_dir = Path(tmp)
            bundle = stub_dir / "bundle"
            bundle.write_text(BUNDLE_STUB)
            bundle.chmod(0o755)
            (stub_dir / "status").write_text(status)
            env = dict(os.environ)
            env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
            env["STUB_DIR"] = tmp
            env["STUB_RC"] = str(rc)
            done = subprocess.run(
                ["bash", str(SCRIPT), "2", "1", "echo", "ENTRYPOINT"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            calls = (
                stub_dir / "calls"
            ).read_text()  # nocheck: cache-read tempdir fixture
            return done.stdout + done.stderr, calls

    def test_a_current_schema_starts_the_entrypoint_at_once(self):
        output, calls = self.run_gate(ALL_UP)
        self.assertIn("schema is current", output)
        self.assertIn("ENTRYPOINT", output)
        self.assertEqual(calls.splitlines(), ["exec rails db:migrate:status"])

    def test_a_pending_migration_keeps_the_gate_waiting(self):
        output, calls = self.run_gate(ONE_DOWN)
        self.assertIn("deadline of 2s reached", output)
        self.assertGreaterEqual(len(calls.splitlines()), 1)

    def test_a_failing_probe_keeps_the_gate_waiting(self):
        output, _ = self.run_gate("", rc=1)
        self.assertIn("deadline of 2s reached", output)

    def test_the_probe_never_builds_a_migrator(self):
        _, calls = self.run_gate(ONE_DOWN)
        self.assertNotIn("abort_if_pending_migrations", calls)
        self.assertEqual(set(calls.splitlines()), {"exec rails db:migrate:status"})


if __name__ == "__main__":
    unittest.main()
