import contextlib
import io
import json
import subprocess
import sys
import types
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

FILES = PROJECT_ROOT / "roles" / "web-app-mailu" / "files" / "python"
DOMAIN = "example.org"
BASE = "http://localhost:8080/api/v1"
READ_CURL = "curl -s --connect-timeout 5 --max-time 30 --retry 3 --retry-all-errors --retry-delay 2"
WRITE_CURL = "curl -s --connect-timeout 5 --max-time 30"
ENVIRON = {
    "RBAC_SYNC_CONTAINER_BIN": "/usr/bin/container",
    "RBAC_SYNC_CID": "c1",
    "MAILU_API_BEARER": "bearer-value",
    "MAILU_API_BASE_URL": BASE,
    "MAILU_DOMAIN": DOMAIN,
    "MAILU_CURL_READ": READ_CURL,
    "MAILU_CURL_WRITE": WRITE_CURL,
    "MAILU_RBAC_KEEP": json.dumps(["platformadmin"]),
}
PREFIX = [
    "/usr/bin/container",
    "exec",
    "-i",
    "-e",
    "MAILU_API_BEARER",
    "c1",
    "sh",
    "-c",
]


def load_module():
    if str(FILES) not in sys.path:
        sys.path.insert(0, str(FILES))
    script = FILES / "rbac_sync.py"
    module = types.ModuleType("mailu_rbac_sync")
    exec(compile(read_text(str(script)), str(script), "exec"), module.__dict__)
    return module


class FakeAdmin:
    def __init__(self, users, managers, status="200"):
        self.users = users
        self.managers = managers
        self.status = status
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs["input"]))
        args = argv[argv.index("_") + 1 :]
        if args[0] == f"{BASE}/user":
            stdout = json.dumps(self.users)
        elif args[0] == f"{BASE}/domain/{DOMAIN}/manager":
            stdout = json.dumps({"managers": self.managers})
        else:
            stdout = self.status
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    def writes(self):
        return [
            (argv[argv.index("_") + 1 :], json.loads(body))
            for argv, body in self.calls
            if len(argv) - argv.index("_") == 3
        ]


def user(local, global_admin=False):
    return {"email": f"{local}@{DOMAIN}", "global_admin": global_admin}


class MailuRbacSyncTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def run_main(self, fake, administrators, managers):
        environ = {
            **ENVIRON,
            "RBAC_ADMINISTRATORS": json.dumps(administrators),
            "RBAC_DOMAIN_MANAGERS": json.dumps(managers),
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(environ, run=fake)
        return stdout.getvalue().splitlines()

    def test_reads_list_users_and_managers_with_the_bearer_left_to_the_container(self):
        fake = FakeAdmin([], [])
        self.run_main(fake, [], [])

        read = (
            f'{READ_CURL} -S --fail -H "Authorization: Bearer $MAILU_API_BEARER" "$1"'
        )
        self.assertEqual(
            [argv for argv, _ in fake.calls],
            [
                [*PREFIX, read, "_", f"{BASE}/user"],
                [*PREFIX, read, "_", f"{BASE}/domain/{DOMAIN}/manager"],
            ],
        )
        for argv, _ in fake.calls:
            self.assertNotIn("bearer-value", " ".join(argv))

    def test_members_are_promoted_and_outsiders_demoted(self):
        fake = FakeAdmin(
            [user("alice"), user("mallory", global_admin=True), user("bob")],
            [f"carol@{DOMAIN}"],
        )
        output = self.run_main(fake, ["Alice"], ["bob"])

        self.assertEqual(
            fake.writes(),
            [
                (["PATCH", f"{BASE}/user/alice@{DOMAIN}"], {"global_admin": True}),
                (["PATCH", f"{BASE}/user/mallory@{DOMAIN}"], {"global_admin": False}),
                (
                    ["POST", f"{BASE}/domain/{DOMAIN}/manager"],
                    {"user_email": f"bob@{DOMAIN}"},
                ),
                (["DELETE", f"{BASE}/domain/{DOMAIN}/manager/carol@{DOMAIN}"], {}),
            ],
        )
        self.assertEqual(
            output,
            [
                f"CHANGED PATCH alice@{DOMAIN} /user/",
                f"CHANGED PATCH mallory@{DOMAIN} /user/",
                f"CHANGED POST bob@{DOMAIN} /domain/{DOMAIN}/manager",
                f"CHANGED DELETE carol@{DOMAIN} /domain/{DOMAIN}/manager/",
            ],
        )

    def test_writes_report_their_status_code_through_curl(self):
        fake = FakeAdmin([user("alice")], [])
        self.run_main(fake, ["alice"], [])

        write = fake.calls[-1][0][len(PREFIX)]
        self.assertTrue(
            write.startswith(
                f'{WRITE_CURL} -S -o /dev/null -w "%{{http_code}}" -X "$1" '
            )
        )
        self.assertTrue(write.endswith('--data-binary @- "$2"'))

    def test_the_kept_administrator_and_a_converged_domain_change_nothing(self):
        fake = FakeAdmin(
            [
                user("platformadmin", global_admin=True),
                user("alice", global_admin=True),
                user("bob"),
            ],
            [f"bob@{DOMAIN}"],
        )
        output = self.run_main(fake, ["alice"], ["bob"])

        self.assertEqual(fake.writes(), [])
        self.assertEqual(output, ["UNCHANGED"])

    def test_a_refused_request_fails_the_run(self):
        fake = FakeAdmin([user("alice")], [], status="403")

        with self.assertRaises(SystemExit) as raised:
            self.run_main(fake, ["alice"], [])
        self.assertIn("HTTP 403", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
