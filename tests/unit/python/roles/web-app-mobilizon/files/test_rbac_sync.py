import contextlib
import io
import json
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

FILES = PROJECT_ROOT / "roles" / "web-app-mobilizon" / "files"
SCRIPT = FILES / "python" / "rbac_sync.py"
PROGRAM = FILES / "elixir" / "rbac.exs"
ENVIRON = {
    "RBAC_SYNC_CONTAINER_BIN": "/usr/bin/container",
    "RBAC_SYNC_CID": "c1",
    "MOBILIZON_CLI": "/bin/mobilizon",
    "MOBILIZON_RBAC_BOOTSTRAP": "administrator@example.org",
    "MOBILIZON_RBAC_PROVIDER": "keycloak",
}


def load_into_hook_dir(hook_dir):
    (hook_dir / "rbac.exs").write_text(read_text(str(PROGRAM)), encoding="utf-8")
    module = types.ModuleType("mobilizon_rbac_sync")
    module.__file__ = str(hook_dir / "main.py")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


class FakeRpc:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if kwargs["check"] and self.returncode:
            raise subprocess.CalledProcessError(self.returncode, argv)
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout)


class MobilizonRbacSyncTests(unittest.TestCase):
    def setUp(self):
        self.hook_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.hook_dir.cleanup)
        self.mod = load_into_hook_dir(Path(self.hook_dir.name))

    def run_main(self, fake, administrators=(), moderators=()):
        environ = {
            **ENVIRON,
            "RBAC_ADMINISTRATORS": json.dumps(list(administrators)),
            "RBAC_MODERATORS": json.dumps(list(moderators)),
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(environ, fake)
        return stdout.getvalue().splitlines()

    def test_the_program_runs_through_rpc_with_the_members_on_stdin(self):
        fake = FakeRpc(
            "CHANGED alice@example.org created\n"
            "CHANGED alice@example.org role=administrator\n"
            "MOBILIZON_RBAC=done\n"
        )
        output = self.run_main(fake, ["alice@example.org", ""], ["bob@example.org"])

        argv, kwargs = fake.calls[0]
        self.assertEqual(
            argv,
            [
                "/usr/bin/container",
                "exec",
                "-i",
                "c1",
                "/bin/mobilizon",
                "rpc",
                read_text(str(PROGRAM)),
            ],
        )
        self.assertEqual(
            json.loads(kwargs["input"]),
            {
                "administrators": ["alice@example.org"],
                "moderators": ["bob@example.org"],
                "bootstrap": "administrator@example.org",
                "provider": "keycloak",
            },
        )
        self.assertEqual(
            output,
            [
                "CHANGED alice@example.org created",
                "CHANGED alice@example.org role=administrator",
            ],
        )

    def test_a_converged_instance_reports_unchanged(self):
        output = self.run_main(FakeRpc("MOBILIZON_RBAC=done\n"), ["alice@example.org"])

        self.assertEqual(output, ["UNCHANGED"])

    def test_output_without_the_completion_marker_fails_the_hook(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_main(
                FakeRpc("CHANGED alice@example.org created\n"), ["alice@example.org"]
            )

        self.assertIn("MOBILIZON_RBAC=done", str(raised.exception.code))

    def test_a_failing_rpc_fails_the_hook(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_main(FakeRpc("", returncode=1), ["alice@example.org"])

    def test_the_rpc_stderr_is_left_to_the_runner(self):
        fake = FakeRpc("MOBILIZON_RBAC=done\n")
        self.run_main(fake)

        _, kwargs = fake.calls[0]
        self.assertNotIn("stderr", kwargs)
        self.assertNotIn("capture_output", kwargs)


if __name__ == "__main__":
    unittest.main()
