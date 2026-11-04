import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

SCRIPT = PROJECT_ROOT / "roles/web-app-keycloak/files/shell/ensure_realm_user.sh"
CALLER = PROJECT_ROOT / "roles/web-app-keycloak/tasks/update/06_users/realm.yml"
USER_ID = "0f0e0d0c-0b0a-0908-0706-050403020100"
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
KCADM = f"""#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_LOG/argv"
case "$1 $2" in
  "get users") printf 'id\\n{USER_ID}\\n' ;;
  "update users/{USER_ID}/reset-password") cat > "$STUB_LOG/credential" ;;
esac
"""


class TestEnsureRealmUser(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name, body in (("container", CONTAINER), ("kcadm.sh", KCADM)):
            stub = self.root / name
            stub.write_text(body)
            stub.chmod(0o755)

    def _run(self, stdin: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PATH": f"{self.root}:{os.environ['PATH']}",
            "STUB_LOG": str(self.root),
            "KEYCLOAK_EXEC_CONTAINER": "container exec -i keycloak",
            "KEYCLOAK_KCADM": str(self.root / "kcadm.sh"),
            "KEYCLOAK_REALM": "infinito",
            "KEYCLOAK_USERNAME": "alice",
            "KEYCLOAK_UIDNUMBER": "1001",
        }
        return subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )

    def _read(self, name: str) -> str:
        path = self.root / name
        return path.read_text()  # nocheck: cache-read  the stubs just wrote it

    def test_the_credential_reaches_kcadm_on_stdin_unchanged(self) -> None:
        for password in PASSWORDS:
            with self.subTest(password=password):
                (self.root / "argv").unlink(missing_ok=True)
                credential = json.dumps(
                    {"type": "password", "value": password, "temporary": False}
                )
                proc = self._run(credential + "\n")
                self.assertEqual(0, proc.returncode, proc.stderr)
                self.assertEqual(
                    json.loads(self._read("credential"))["value"], password
                )

    def test_no_argv_carries_the_password(self) -> None:
        for password in PASSWORDS:
            with self.subTest(password=password):
                (self.root / "argv").unlink(missing_ok=True)
                credential = json.dumps(
                    {"type": "password", "value": password, "temporary": False}
                )
                self.assertEqual(0, self._run(credential + "\n").returncode)
                argv = self._read("argv")
                self.assertIn("reset-password", argv)
                self.assertNotIn("S3cr3t", argv)

    def test_an_empty_stdin_fails_naming_the_credential(self) -> None:
        proc = self._run("")
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("missing the credential on stdin", proc.stderr)
        self.assertFalse((self.root / "argv").exists())


class TestRealmUserCaller(unittest.TestCase):
    def _task(self) -> dict:
        return next(
            task
            for task in load_yaml_any(str(CALLER))
            if "ensure_realm_user.sh" in task["ansible.builtin.shell"]["cmd"]
        )

    def test_the_caller_hands_the_credential_on_stdin(self) -> None:
        environment = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        environment.filters["to_json"] = json.dumps
        for password in PASSWORDS:
            with self.subTest(password=password):
                rendered = environment.from_string(
                    self._task()["ansible.builtin.shell"]["stdin"]
                ).render(item={"value": {"password": password}})
                self.assertEqual(json.loads(rendered)["value"], password)
                self.assertNotIn("\n", rendered)

    def test_the_caller_environment_carries_no_password(self) -> None:
        environment = self._task()["environment"]
        self.assertNotIn("password", " ".join(map(str, environment.values())))
        self.assertNotIn("PASSWORD", " ".join(environment))


if __name__ == "__main__":
    unittest.main()
