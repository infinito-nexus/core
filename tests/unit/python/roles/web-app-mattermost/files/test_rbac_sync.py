import contextlib
import io
import json
import subprocess
import sys
import types
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

FILES = PROJECT_ROOT / "roles" / "web-app-mattermost" / "files" / "python"
ENVIRON = {
    "RBAC_SYNC_CONTAINER_BIN": "/usr/bin/container",
    "RBAC_SYNC_CID": "c1",
    "MATTERMOST_MMCTL": "/mattermost/bin/mmctl",
    "MATTERMOST_RBAC_KEEP": json.dumps(["platformadmin"]),
}


def load_module():
    if str(FILES) not in sys.path:
        sys.path.insert(0, str(FILES))
    script = FILES / "rbac_sync.py"
    module = types.ModuleType("mattermost_rbac_sync")
    exec(compile(read_text(str(script)), str(script), "exec"), module.__dict__)
    return module


class FakeMmctl:
    def __init__(self, users):
        self.users = users
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        stdout = json.dumps(self.users) if "list" in argv else ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


def user(username, roles="system_user"):
    return {"username": username, "email": f"{username}@example.org", "roles": roles}


class MattermostRbacSyncTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def run_main(self, users, administrators):
        environ = {**ENVIRON, "RBAC_ADMINISTRATORS": json.dumps(administrators)}
        fake = FakeMmctl(users)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(environ, run=fake)
        return fake.calls, stdout.getvalue().splitlines()

    def test_members_are_promoted_and_outsiders_demoted_through_mmctl(self):
        calls, output = self.run_main(
            [user("alice"), user("mallory", "system_admin system_user")],
            [{"username": "alice", "email": "alice@example.org"}],
        )

        prefix = [
            "/usr/bin/container",
            "exec",
            "-i",
            "c1",
            "/mattermost/bin/mmctl",
            "--local",
        ]
        self.assertEqual(
            calls,
            [
                [*prefix, "--json", "--suppress-warnings", "user", "list", "--all"],
                [*prefix, "roles", "system_admin", "alice"],
                [*prefix, "roles", "member", "mallory"],
            ],
        )
        self.assertEqual(
            output, ["CHANGED alice system_admin", "CHANGED mallory member"]
        )

    def test_the_kept_administrator_and_a_converged_team_change_nothing(self):
        calls, output = self.run_main(
            [user("platformadmin", "system_admin"), user("alice", "system_admin")],
            [{"username": "alice", "email": "alice@example.org"}],
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(output, ["UNCHANGED"])


if __name__ == "__main__":
    unittest.main()
