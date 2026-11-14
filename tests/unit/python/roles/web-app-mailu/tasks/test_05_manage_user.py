import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles/web-app-mailu/tasks/05_manage_user.yml"
TASK_NAMES = ("✅ Ensure user", "🔧 Set password")
SHELLS = tuple(shell for shell in ("/bin/sh", "/usr/bin/dash") if Path(shell).exists())
PASSWORDS = (
    "S3cr3t with space",
    "S3cr3t'single\"double",
    "S3cr3t$HOME$(id)`id`",
    "S3cr3t\\back\\slash",
    "S3cr3t trailing  ",
)
CONTAINER = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_LOG/argv"
shift
while [ "$#" -gt 0 ]; do
  case "$1" in
    -e|-u|-w) shift 2 ;;
    -*) shift ;;
    *) shift; break ;;
  esac
done
exec "$@"
"""
FLASK = """#!/bin/sh
for argument in "$@"; do last="$argument"; done
printf '%s' "$last" > "$STUB_LOG/password"
"""


def _command(prefix: str) -> str:
    task = next(
        task
        for task in load_yaml_any(str(TASKS))[0]["block"]
        if task["name"].startswith(prefix)
    )
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["quote"] = shlex.quote
    return environment.from_string(task["ansible.builtin.shell"]).render(
        MAILU_ADMIN_CONTAINER_ADDRESS="mailu-admin",
        mailu_action="user",
        mailu_user_name="alice",
        MAILU_DOMAIN="example.org",
    )


class TestManageUserStdin(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name, body in (("container", CONTAINER), ("flask", FLASK)):
            stub = self.root / name
            stub.write_text(body)
            stub.chmod(0o755)

    def _run(self, shell: str, prefix: str, stdin: str) -> subprocess.CompletedProcess:
        for log in ("argv", "password"):
            (self.root / log).unlink(missing_ok=True)
        return subprocess.run(
            [shell, "-c", _command(prefix)],
            env={
                **os.environ,
                "PATH": f"{self.root}:{os.environ['PATH']}",
                "STUB_LOG": str(self.root),
            },
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )

    def _read(self, name: str) -> str:
        path = self.root / name
        return path.read_text()  # nocheck: cache-read  the stub just wrote it

    def test_the_password_reaches_flask_unchanged(self) -> None:
        for shell in SHELLS:
            for prefix in TASK_NAMES:
                for password in PASSWORDS:
                    with self.subTest(shell=shell, task=prefix, password=password):
                        proc = self._run(shell, prefix, password + "\n")
                        self.assertEqual(0, proc.returncode, proc.stderr)
                        self.assertEqual(self._read("password"), password)

    def test_the_host_exec_argv_carries_no_password(self) -> None:
        for prefix in TASK_NAMES:
            with self.subTest(task=prefix):
                self.assertEqual(
                    0, self._run(SHELLS[0], prefix, PASSWORDS[2] + "\n").returncode
                )
                argv = self._read("argv")
                self.assertIn("-e MAILU_USER_PASSWORD mailu-admin", argv)
                self.assertNotIn("S3cr3t", argv)

    def test_an_empty_stdin_fails_naming_the_variable(self) -> None:
        for shell in SHELLS:
            for prefix in TASK_NAMES:
                with self.subTest(shell=shell, task=prefix):
                    proc = self._run(shell, prefix, "")
                    self.assertNotEqual(0, proc.returncode)
                    self.assertIn(
                        "MAILU_USER_PASSWORD: arrived empty on stdin", proc.stderr
                    )
                    self.assertFalse((self.root / "argv").exists())


if __name__ == "__main__":
    unittest.main()
