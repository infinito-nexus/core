from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from types import SimpleNamespace

from cli.administration.deploy.dedicated import command
from tests.utils.openbao_stub import OpenBaoStub
from utils import openbao_client

ROLE = "ws-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
TASK_JWT = "eyJ.task-token.sig"
TASK_TOKEN = "s.task-login-token"
OPERATOR_TOKEN = "s.operator-token"
VALUE = "known-secret-value-4711"
HOST_VARS = """applications:
  web-app-foo:
    secrets:
      credentials:
        ssh:
          openbao: tenant/{role}/ssh#private_key
        nested:
          admin:
            openbao: tenant/{role}/admin#password
        vaulted: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          6162636465
        plain: not-a-reference
"""


class TestTheDeployLogsInToOpenBao(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.stub = OpenBaoStub(
            tokens={
                TASK_TOKEN: [f"tenant/{ROLE}/"],
                OPERATOR_TOKEN: [f"tenant/{ROLE}/"],
            },
            logins={(ROLE, TASK_JWT): TASK_TOKEN},
        )
        cls.stub.put(f"tenant/{ROLE}/ssh", {"private_key": VALUE})
        cls.stub.put(f"tenant/{ROLE}/admin", {"password": VALUE + "-admin"})
        cls.addClassCleanup(cls.stub.close)

    def setUp(self) -> None:
        openbao_client._SESSION.clear()
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        root = Path(self._dir.name)
        (root / "host_vars").mkdir()
        self.host_vars = root / "host_vars" / "host.example.yml"
        self.write_host_vars(HOST_VARS.format(role=ROLE))
        self.inventory = root / "devices.yml"
        self.inventory.write_text(
            "all:\n  hosts:\n    host.example: {}\n", encoding="utf-8"
        )

    def write_host_vars(self, text: str) -> None:
        self.host_vars.write_text(text, encoding="utf-8")

    def deploy(self, environ: dict[str, str]) -> tuple[mock.MagicMock, str, str, int]:
        """
        Args:
            environ: the OpenBao variables of the controller's environment.

        Returns:
            The playbook runner stand-in, stdout, stderr and the exit status.
        """
        base = {"BAO_ADDR": self.stub.addr, "BAO_CACERT": self.stub.cafile}
        cleared = {
            key: ""
            for key in ("SEMAPHORE_JWT", "BAO_ROLE", "BAO_TOKEN")
            if key not in environ
        }
        args = SimpleNamespace(
            inventory=str(self.inventory),
            id=[],
            limit=None,
            password_file=None,
            verbose=0,
            skip_build=True,
            diff=False,
        )
        stdout, stderr = io.StringIO(), io.StringIO()
        status = 0
        with (
            mock.patch.dict(os.environ, {**base, **cleared, **environ}),
            mock.patch.object(command, "validate_application_ids"),
            mock.patch.object(command, "build_modes_from_args", return_value={}),
            mock.patch.object(command, "run_ansible_playbook") as runner,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            try:
                command.run_from_args(args, [], {})
            except SystemExit as exc:
                status = int(exc.code or 0)
            self.token_for_play = os.environ.get("BAO_TOKEN", "")
        return runner, stdout.getvalue(), stderr.getvalue(), status

    def test_the_cli_logs_in_once_with_the_task_token(self) -> None:
        logins = self.stub.login_count
        runner, _, stderr, status = self.deploy(
            {"SEMAPHORE_JWT": TASK_JWT, "BAO_ROLE": ROLE}
        )
        self.assertEqual(status, 0, stderr)
        self.assertEqual(self.stub.login_count - logins, 1)
        self.assertEqual(self.token_for_play, TASK_TOKEN)
        runner.assert_called_once()
        self.assertNotIn(TASK_TOKEN, repr(runner.call_args))
        for path in Path(self._dir.name).rglob("*"):  # nocheck: project-walk tempdir
            if path.is_file():
                text = path.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
                self.assertNotIn(TASK_TOKEN, text)

    def test_the_cli_falls_back_to_an_operator_token(self) -> None:
        logins = self.stub.login_count
        runner, _, stderr, status = self.deploy({"BAO_TOKEN": OPERATOR_TOKEN})
        self.assertEqual(status, 0, stderr)
        self.assertEqual(self.stub.login_count, logins)
        self.assertEqual(self.token_for_play, OPERATOR_TOKEN)
        runner.assert_called_once()

    def test_a_reference_without_a_login_stops_the_deploy(self) -> None:
        runner, _, stderr, status = self.deploy({})
        self.assertEqual(status, 1)
        runner.assert_not_called()
        self.assertIn("no OpenBao login", stderr)
        self.assertIn("SEMAPHORE_JWT", stderr)
        self.assertIn("BAO_TOKEN", stderr)

    def test_an_inventory_without_references_needs_no_login(self) -> None:
        self.write_host_vars("applications:\n  web-app-foo:\n    secrets: {}\n")
        logins = self.stub.login_count
        runner, _, stderr, status = self.deploy({})
        self.assertEqual(status, 0, stderr)
        self.assertEqual(self.stub.login_count, logins)
        runner.assert_called_once()

    def test_a_missing_path_stops_before_the_play(self) -> None:
        self.write_host_vars(
            HOST_VARS.format(role=ROLE).replace("/ssh#private_key", "/gone#private_key")
        )
        runner, _, stderr, status = self.deploy({"BAO_TOKEN": OPERATOR_TOKEN})
        self.assertEqual(status, 1)
        runner.assert_not_called()
        self.assertIn(f"tenant/{ROLE}/gone", stderr)
        self.assertIn("private_key", stderr)
        self.assertIn("HTTP 404", stderr)

    def test_a_denied_path_stops_before_the_play(self) -> None:
        other = "ws-9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f"
        self.write_host_vars(
            HOST_VARS.format(role=ROLE).replace(
                f"tenant/{ROLE}/ssh", f"tenant/{other}/ssh"
            )
        )
        runner, _, stderr, status = self.deploy(
            {"SEMAPHORE_JWT": TASK_JWT, "BAO_ROLE": ROLE}
        )
        self.assertEqual(status, 1)
        runner.assert_not_called()
        self.assertIn(f"tenant/{other}/ssh", stderr)
        self.assertIn("private_key", stderr)
        self.assertIn("HTTP 403", stderr)

    def test_a_refused_task_token_stops_before_the_play(self) -> None:
        runner, _, stderr, status = self.deploy(
            {"SEMAPHORE_JWT": "eyJ.other-task.sig", "BAO_ROLE": ROLE}
        )
        self.assertEqual(status, 1)
        runner.assert_not_called()
        self.assertIn(f"role {ROLE}", stderr)

    def test_an_erased_person_stops_the_deploy_before_the_play(self) -> None:
        personal = "".join(
            f"    {field}:\n      openbao: tenant/{ROLE}/users/alice#{field}\n"
            for field in ("email", "firstname", "lastname")
        )
        self.write_host_vars(
            HOST_VARS.format(role=ROLE) + "users:\n  alice:\n" + personal
        )
        runner, stdout, stderr, status = self.deploy({"BAO_TOKEN": OPERATOR_TOKEN})
        self.assertEqual(status, 1)
        runner.assert_not_called()
        self.assertIn(f"tenant/{ROLE}/users/alice", stderr)
        self.assertIn("users.alice.email", stderr)
        self.assertIn("HTTP 404", stderr)
        for output in (stdout, stderr):
            self.assertNotIn(VALUE, output)

    def test_a_personal_field_is_read_but_never_printed(self) -> None:
        email = "alice.private@example.net"
        self.stub.put(f"tenant/{ROLE}/users/bob", {"email": email})
        self.write_host_vars(
            HOST_VARS.format(role=ROLE)
            + f"users:\n  bob:\n    email:\n      openbao: tenant/{ROLE}/users/bob#email\n"
        )
        runner, stdout, stderr, status = self.deploy({"BAO_TOKEN": OPERATOR_TOKEN})
        self.assertEqual(status, 0, stderr)
        runner.assert_called_once()
        for output in (stdout, stderr, repr(runner.call_args)):
            self.assertNotIn(email, output)

    def test_no_resolved_value_reaches_the_output(self) -> None:
        outputs: list[str] = []
        _, stdout, stderr, _ = self.deploy({"BAO_TOKEN": OPERATOR_TOKEN})
        outputs += [stdout, stderr]
        self.write_host_vars(
            HOST_VARS.format(role=ROLE).replace("#private_key", "#missing_field")
        )
        _, stdout, stderr, status = self.deploy({"BAO_TOKEN": OPERATOR_TOKEN})
        self.assertEqual(status, 1)
        outputs += [stdout, stderr]
        for output in outputs:
            self.assertNotIn(VALUE, output)
            self.assertNotIn(OPERATOR_TOKEN, output)


class TestTheReferenceNames(unittest.TestCase):
    def test_a_malformed_reference_stops_the_preflight_with_its_credential(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            (root / "host_vars").mkdir()
            (root / "host_vars" / "h.yml").write_text(
                "applications:\n  web-app-foo:\n    secrets:\n      credentials:\n"
                "        ssh: {openbao: tenant/x, extra: y}\n",
                encoding="utf-8",
            )
            inventory = root / "devices.yml"
            inventory.write_text("all: {}\n", encoding="utf-8")
            with self.assertRaises(command.OpenBaoPreflightError) as caught:
                command.openbao_prepare(str(inventory), {})
        self.assertIn("web-app-foo.secrets.credentials.ssh", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
