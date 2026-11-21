import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles/svc-db-mariadb/tasks"
SHELLS = tuple(shell for shell in ("/bin/sh", "/usr/bin/dash") if Path(shell).exists())
PASSWORDS = (
    "S3cr3t with space",
    "S3cr3t'single\"double",
    "S3cr3t$HOME$(id)`id`",
    "S3cr3t\\back\\slash",
    "S3cr3t trailing  ",
)
ROOT_LOGINS = {
    "00_core.yml: 🔎 Root password reset | Check login with desired password (inside container)",
    "00_core.yml: ⏳ Wait until MariaDB accepts root credentials (inside container)",
    "01_init.yml: 📁 Create database: {{ database_name }} (container via mariadb CLI)",
    "01_init.yml: 📁 Create database user + grant privileges (container via mariadb CLI)",
}
CLIENT = re.compile(r"(?<![\w-])mariadb(?![\w-])")
PASSWORD_FLAG = re.compile(r"(?<![\w-])(?:-p|--password)")
SQL = "SELECT 1;\n"
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
MARIADB = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_LOG/argv"
printf '%s' "$MYSQL_PWD" > "$STUB_LOG/password"
cat > "$STUB_LOG/sql"
"""


def _tasks(node):
    for task in node:
        yield task
        for key in ("block", "rescue", "always"):
            yield from _tasks(task.get(key, []))


def _command(task) -> str | None:
    for key in ("ansible.builtin.shell", "ansible.builtin.command", "shell", "command"):
        body = task.get(key)
        if isinstance(body, dict):
            body = body.get("cmd") or " ".join(map(str, body.get("argv", [])))
        if isinstance(body, str):
            return body
    return None


def _client_calls() -> dict[str, str]:
    found = {}
    for path in sorted(ROLE.glob("*.yml")):
        for task in _tasks(load_yaml_any(str(path)) or []):
            command = _command(task)
            if command and CLIENT.search(command):
                found[f"{path.name}: {task['name']}"] = command
    return found


def _root_logins() -> dict[str, str]:
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    return {
        f"{label} ({expose})": environment.from_string(command).render(
            MARIADB_CONTAINER_ADDRESS="mariadb", MARIADB_EXPOSE_LOCAL=expose
        )
        for label, command in _client_calls().items()
        if label in ROOT_LOGINS
        for expose in (True, False)
    }


class TestRootPasswordStaysInTheContainer(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name, body in (("container", CONTAINER), ("mariadb", MARIADB)):
            stub = self.root / name
            stub.write_text(body)
            stub.chmod(0o755)

    def _run(
        self, shell: str, command: str, password: str
    ) -> subprocess.CompletedProcess:
        for log in ("argv", "password", "sql"):
            (self.root / log).unlink(missing_ok=True)
        return subprocess.run(
            [shell, "-c", command],
            env={
                **os.environ,
                "PATH": f"{self.root}:{os.environ['PATH']}",
                "STUB_LOG": str(self.root),
                "MARIADB_ROOT_PASSWORD": password,
            },
            input=SQL,
            capture_output=True,
            text=True,
            check=False,
        )

    def _read(self, name: str) -> str:
        path = self.root / name
        return path.read_text()  # nocheck: cache-read  the stub just wrote it

    def test_every_root_login_is_found(self) -> None:
        self.assertLessEqual(ROOT_LOGINS, set(_client_calls()))

    def test_no_client_call_carries_a_password_flag(self) -> None:
        for label, command in _client_calls().items():
            with self.subTest(task=label):
                self.assertIsNone(PASSWORD_FLAG.search(command))

    def test_the_flag_check_rejects_a_password_on_the_client_argv(self) -> None:
        self.assertIsNotNone(PASSWORD_FLAG.search('exec mariadb -p"$X" -uroot'))
        self.assertIsNotNone(PASSWORD_FLAG.search("mariadb --password=$X"))

    def test_mariadb_gets_the_container_password_and_the_sql(self) -> None:
        for label, command in _root_logins().items():
            for shell in SHELLS:
                for password in PASSWORDS:
                    with self.subTest(task=label, shell=shell, password=password):
                        proc = self._run(shell, command, password)
                        self.assertEqual(0, proc.returncode, proc.stderr)
                        self.assertEqual(self._read("password"), password)
                        self.assertEqual(self._read("sql"), SQL)

    def test_no_argv_carries_the_password(self) -> None:
        for label, command in _root_logins().items():
            with self.subTest(task=label):
                self.assertEqual(
                    0, self._run(SHELLS[0], command, PASSWORDS[2]).returncode
                )
                argv = self._read("argv")
                self.assertIn("-uroot", argv)
                self.assertNotIn("S3cr3t", argv)


if __name__ == "__main__":
    unittest.main()
