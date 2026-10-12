import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT

TEMPLATE_DIR = PROJECT_ROOT / "roles/sys-ctl-alm-email/templates"

EMPTY_REPLY = "sendmail: the server sent an empty reply"

SENDMAIL_STUB = """#!/usr/bin/env bash
cat >/dev/null
calls=$(( $(cat "${STUB_DIR}/calls" 2>/dev/null || echo 0) + 1 ))
echo "${calls}" >"${STUB_DIR}/calls"
if [ "${calls}" -gt "${STUB_FAILURES}" ]; then
\texit 0
fi
echo "${STUB_MESSAGE}" >&2
exit "${STUB_RC}"
"""

QUIET_STUB = """#!/usr/bin/env bash
exit 0
"""

ECHO_STUB = """#!/usr/bin/env bash
printf '%s\\n' "${@: -1}"
"""


def lookup(name, *_args):
    """Return what the template's two lookups resolve to.

    Args:
        name: lookup plugin the template calls.
    """
    return {
        "email": {"from": "no-reply@example.test", "timeout": "30"},
        "users": {"email": "administrator@example.test"},
    }[name]


def rendered_script() -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    return env.get_template("script.sh.j2").render(lookup=lookup, HOST_CS="utf-8")


class TestAlmEmailScript(unittest.TestCase):
    def run_script(self, *, failures, rc, message):
        """Run the rendered alarm script against a stubbed sendmail.

        Args:
            failures: how many sendmail calls fail before one succeeds.
            rc: exit code of a failing call.
            message: what a failing call prints to stderr.

        Returns:
            Tuple of the exit code, the retry lines and the whole stderr.
        """
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            stubs = (
                ("sendmail", SENDMAIL_STUB),
                ("sleep", QUIET_STUB),
                ("systemctl", QUIET_STUB),
                ("systemd-escape", ECHO_STUB),
            )
            for name, body in stubs:
                stub = bin_dir / name
                stub.write_text(body)
                stub.chmod(0o755)
            script = bin_dir / "script.sh"
            script.write_text(rendered_script())
            env = dict(os.environ)
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["STUB_DIR"] = tmp
            env["STUB_FAILURES"] = str(failures)
            env["STUB_RC"] = str(rc)
            env["STUB_MESSAGE"] = message
            done = subprocess.run(
                ["bash", str(script), "example.service"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            retries = [
                line
                for line in done.stderr.splitlines()
                if "sendmail transient failure" in line
            ]
            return done.returncode, retries, done.stderr

    def test_a_dropped_connection_is_retried_and_the_alarm_is_sent(self):
        code, retries, _ = self.run_script(failures=1, rc=76, message=EMPTY_REPLY)
        self.assertEqual(code, 0)
        self.assertEqual(len(retries), 1)
        self.assertIn("(rc=76), attempt 1/3", retries[0])

    def test_a_permanent_rejection_is_reported_without_a_retry(self):
        rejection = "sendmail: recipient address rejected"
        code, retries, stderr = self.run_script(failures=99, rc=65, message=rejection)
        self.assertEqual(code, 65)
        self.assertEqual(retries, [])
        self.assertIn(rejection, stderr)

    def test_the_third_failure_ends_the_alarm_with_the_last_exit_code(self):
        code, retries, stderr = self.run_script(failures=99, rc=76, message=EMPTY_REPLY)
        self.assertEqual(code, 76)
        self.assertEqual(len(retries), 2)
        self.assertIn(EMPTY_REPLY, stderr)


if __name__ == "__main__":
    unittest.main()
