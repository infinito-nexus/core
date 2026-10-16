import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/sys-ctl-hlth-journalctl/files/python/script.py"

JOURNALCTL_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >"${STUB_DIR}/args"
cat "${STUB_DIR}/journal"
if [ "${STUB_RC}" -ne 0 ]; then
\techo "journalctl: unrecognized option '--output-fields'" >&2
fi
exit "${STUB_RC}"
"""

APP_ERROR = {
    "MESSAGE": "ERROR: pixelfed queue failed",
    "CONTAINER_ID": "0123456789ab",
    "SYSLOG_IDENTIFIER": "pixelfed",
    "_SYSTEMD_UNIT": "docker.service",
}
DAEMON_ERROR = {
    "MESSAGE": 'level=error msg="failed to start container"',
    "SYSLOG_IDENTIFIER": "dockerd",
    "_SYSTEMD_UNIT": "docker.service",
}
KERNEL_ERROR = {"MESSAGE": "EXT4-fs error (device sda1)", "SYSLOG_IDENTIFIER": "kernel"}
BINARY_ERROR = {
    "MESSAGE": list(b"I/O error \xff on disk"),
    "_SYSTEMD_UNIT": "smartd.service",
}
REPEATED_ERROR = {
    "MESSAGE": ["unit started", list(b"disk error \xff on sdb")],
    "_SYSTEMD_UNIT": "zfs-import.service",
}
SYSTEM_INFO = {
    "MESSAGE": "Started Daily apt download activities.",
    "_SYSTEMD_UNIT": "init.scope",
}


class TestHlthJournalctlScript(unittest.TestCase):
    def run_script(self, *entries, rc=0):
        """Run the health script against a stubbed journalctl.

        Args:
            entries: journal entries the stub prints, one JSON object per line.
            rc: exit code of the stubbed journalctl.

        Returns:
            Tuple of the exit code, the script output, and the journalctl arguments.
        """
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            stub = bin_dir / "journalctl"
            stub.write_text(JOURNALCTL_STUB)
            stub.chmod(0o755)
            (bin_dir / "journal").write_text(
                "".join(json.dumps(entry) + "\n" for entry in entries)
            )
            env = dict(os.environ)
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["STUB_DIR"] = tmp
            env["STUB_RC"] = str(rc)
            done = subprocess.run(
                [sys.executable, str(SCRIPT)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            args = (bin_dir / "args").read_text()  # nocheck: cache-read tempdir fixture
            return done.returncode, done.stdout, args

    def test_reads_the_journal_as_json_with_the_source_fields(self):
        _, _, args = self.run_script(SYSTEM_INFO)
        self.assertIn("--output=json", args)
        self.assertIn(
            "--output-fields=MESSAGE,CONTAINER_ID,SYSLOG_IDENTIFIER,_SYSTEMD_UNIT",
            args,
        )

    def test_reads_every_field_in_full(self):
        _, _, args = self.run_script(SYSTEM_INFO)
        self.assertIn("--all", args.split())

    def test_a_repeated_message_field_is_joined_and_reported(self):
        code, output, _ = self.run_script(REPEATED_ERROR, DAEMON_ERROR)
        self.assertEqual(code, 1)
        self.assertIn("zfs-import.service: unit started disk error", output)
        self.assertIn('docker.service: level=error msg="failed to start', output)

    def test_an_application_error_from_a_container_is_ignored(self):
        code, _, _ = self.run_script(APP_ERROR, SYSTEM_INFO)
        self.assertEqual(code, 0)

    def test_a_docker_daemon_error_is_reported_with_its_unit(self):
        code, output, _ = self.run_script(APP_ERROR, DAEMON_ERROR)
        self.assertEqual(code, 1)
        self.assertIn(
            'docker.service: level=error msg="failed to start container"', output
        )
        self.assertNotIn("pixelfed queue failed", output)

    def test_an_entry_without_unit_is_named_by_its_identifier(self):
        code, output, _ = self.run_script(KERNEL_ERROR)
        self.assertEqual(code, 1)
        self.assertIn("kernel: EXT4-fs error (device sda1)", output)

    def test_a_non_utf8_message_is_decoded_and_reported(self):
        code, output, _ = self.run_script(BINARY_ERROR)
        self.assertEqual(code, 1)
        self.assertIn("smartd.service: I/O error", output)

    def test_many_container_errors_are_streamed_past_and_not_reported(self):
        container_lines = [
            {**APP_ERROR, "MESSAGE": f"ERROR: pixelfed request {n} failed"}
            for n in range(20000)
        ]
        code, output, _ = self.run_script(*container_lines, DAEMON_ERROR)
        self.assertEqual(code, 1)
        self.assertNotIn("pixelfed request", output)
        self.assertEqual(
            output.splitlines()[-1],
            'docker.service: level=error msg="failed to start container"',
        )
        self.assertEqual(len(output.splitlines()), 3)

    def test_a_journal_without_errors_passes(self):
        code, _, _ = self.run_script(SYSTEM_INFO)
        self.assertEqual(code, 0)

    def test_a_failing_journalctl_fails_the_check(self):
        code, output, _ = self.run_script(rc=1)
        self.assertEqual(code, 2)
        self.assertIn("journalctl failed with exit code 1", output)
        self.assertIn("unrecognized option '--output-fields'", output)


if __name__ == "__main__":
    unittest.main()
