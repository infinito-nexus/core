import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/sys-ctl-hlth-msmtp/files/shell/script.sh"

EMPTY_REPLY = "msmtp: the server sent an empty reply"

MSMTP_STUB = """#!/usr/bin/env bash
cat >/dev/null
calls=$(( $(cat "${STUB_DIR}/calls" 2>/dev/null || echo 0) + 1 ))
echo "${calls}" >"${STUB_DIR}/calls"
if [ "${calls}" -gt "${STUB_FAILURES}" ]; then
\texit 0
fi
echo "${STUB_MESSAGE}" >&2
exit "${STUB_RC}"
"""

SLEEP_STUB = """#!/usr/bin/env bash
exit 0
"""


class TestHlthMsmtpScript(unittest.TestCase):
    def run_script(self, *, failures, rc, message):
        """Run the health script against a stubbed msmtp.

        Args:
            failures: how many msmtp calls fail before one succeeds.
            rc: exit code of a failing call.
            message: what a failing call prints to stderr.

        Returns:
            Tuple of the exit code and the retry lines the script printed.
        """
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            for name, body in (("msmtp", MSMTP_STUB), ("sleep", SLEEP_STUB)):
                stub = bin_dir / name
                stub.write_text(body)
                stub.chmod(0o755)
            env = dict(os.environ)
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["MAIL_RECIPIENT"] = "administrator@example.test"
            env["MAIL_TIMEOUT"] = "30"
            env["STUB_DIR"] = tmp
            env["STUB_FAILURES"] = str(failures)
            env["STUB_RC"] = str(rc)
            env["STUB_MESSAGE"] = message
            done = subprocess.run(
                ["bash", str(SCRIPT)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            retries = [
                line
                for line in done.stderr.splitlines()
                if "msmtp transient failure" in line
            ]
            return done.returncode, retries

    def test_a_dropped_connection_is_retried_until_the_mail_is_accepted(self):
        code, retries = self.run_script(failures=1, rc=76, message=EMPTY_REPLY)
        self.assertEqual(code, 0)
        self.assertEqual(len(retries), 1)
        self.assertIn("(rc=76), attempt 1/10", retries[0])

    def test_another_protocol_error_ends_the_check_at_once(self):
        code, retries = self.run_script(
            failures=99,
            rc=76,
            message="msmtp: cannot get initial OK message from server",
        )
        self.assertEqual(code, 76)
        self.assertEqual(retries, [])

    def test_a_server_that_keeps_dropping_fails_after_the_last_attempt(self):
        code, retries = self.run_script(failures=99, rc=76, message=EMPTY_REPLY)
        self.assertEqual(code, 76)
        self.assertEqual(len(retries), 9)


if __name__ == "__main__":
    unittest.main()
