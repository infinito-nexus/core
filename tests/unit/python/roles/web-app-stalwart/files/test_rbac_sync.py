import contextlib
import copy
import io
import json
import subprocess
import sys
import types
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

FILES = PROJECT_ROOT / "roles" / "web-app-stalwart" / "files" / "python"
CURL = "curl -s --connect-timeout 5 --max-time 30 --retry 3 --retry-all-errors --retry-delay 2"
URL = "http://localhost:8080/jmap/"
ENVIRON = {
    "RBAC_SYNC_CONTAINER_BIN": "/usr/bin/container",
    "RBAC_SYNC_CID": "c1",
    "STALWART_CURL": CURL,
    "STALWART_JMAP_URL": URL,
    "STALWART_JMAP_TRANSIENT_ERRORS": json.dumps(["serverUnavailable", "rateLimit"]),
    "STALWART_ADMIN_USER": "stalwartadmin",
    "STALWART_ADMIN_PASSWORD": "recovery-password",
    "STALWART_DOMAIN": "example.test",
    "STALWART_RBAC_KEEP": json.dumps(["stalwartadmin", "platformadmin"]),
}
ADMIN = {"r-admin": True, "r-user": True}
USER = {"r-user": True}


def load_module():
    if str(FILES) not in sys.path:
        sys.path.insert(0, str(FILES))
    script = FILES / "rbac_sync.py"
    module = types.ModuleType("stalwart_rbac_sync")
    exec(compile(read_text(str(script)), str(script), "exec"), module.__dict__)
    return module


def account(account_id, name, role_ids=None, domain="d1", kind="User"):
    entry = {"id": account_id, "name": name, "@type": kind, "domainId": domain}
    if role_ids is not None:
        entry["roles"] = {"@type": "Custom", "roleIds": dict(role_ids)}
    return entry


class FakeStalwart:
    def __init__(self, accounts, refuse_update=False, sticky_admin=(), errors=()):
        self.accounts = {entry["id"]: entry for entry in accounts}
        self.refuse_update = refuse_update
        self.sticky_admin = set(sticky_admin)
        self.errors = list(errors)
        self.calls = []
        self.configs = []

    def __call__(self, argv, **kwargs):
        lines = dict(line.split(" = ", 1) for line in kwargs["input"].splitlines())
        self.configs.append(json.loads(lines["user"]))
        request = json.loads(json.loads(lines["data-binary"]))
        method, arguments, _ = request["methodCalls"][0]
        self.calls.append((argv, method, arguments))
        if self.errors:
            response = ["error", {"type": self.errors.pop(0)}, "c0"]
        else:
            response = [method, self.answer(method, arguments), "c0"]
        stdout = json.dumps({"methodResponses": [response]})
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    def answer(self, method, arguments):
        if method == "x:Domain/get":
            return {
                "list": [
                    {"id": "d2", "name": "other.test"},
                    {"id": "d1", "name": "example.test"},
                ]
            }
        if method == "x:Role/get":
            return {
                "list": [
                    {"id": "r-user", "description": "User"},
                    {"id": "r-admin", "description": "System Administrator"},
                ]
            }
        if method == "x:Account/get":
            ids = (
                arguments["ids"]
                if arguments["ids"] is not None
                else list(self.accounts)
            )
            return {
                "list": [
                    copy.deepcopy(self.accounts[i]) for i in ids if i in self.accounts
                ]
            }
        if self.refuse_update:
            return {
                "notUpdated": {next(iter(arguments["update"])): {"type": "forbidden"}}
            }
        for account_id, patch in arguments["update"].items():
            if account_id not in self.sticky_admin:
                self.accounts[account_id]["roles"] = copy.deepcopy(patch["roles"])
        return {"updated": dict.fromkeys(arguments["update"])}

    def methods(self):
        return [method for _, method, _ in self.calls]


class StalwartRbacSyncTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.sleeps = []

    def run_main(self, fake, administrators):
        environ = {**ENVIRON, "RBAC_ADMINISTRATORS": json.dumps(administrators)}
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(environ, run=fake, sleep=self.sleeps.append)
        return stdout.getvalue().splitlines()

    def test_members_are_granted_and_other_holders_stripped(self):
        fake = FakeStalwart(
            [
                account("p1", "platformadmin", ADMIN),
                account("a1", "alice", USER),
                account("m1", "mallory", ADMIN),
                account("b1", "biber", USER),
            ]
        )
        output = self.run_main(fake, ["alice"])

        self.assertEqual(
            output, ["CHANGED alice system-administrator", "CHANGED mallory user"]
        )
        update = [
            arguments
            for _, method, arguments in fake.calls
            if method == "x:Account/set"
        ]
        self.assertEqual(
            update,
            [
                {
                    "update": {
                        "a1": {"roles": {"@type": "Custom", "roleIds": ADMIN}},
                        "m1": {"roles": {"@type": "Custom", "roleIds": USER}},
                    }
                }
            ],
        )
        self.assertEqual(fake.accounts["b1"]["roles"]["roleIds"], USER)
        self.assertEqual(fake.methods()[-1], "x:Account/get")

    def test_a_converged_server_writes_nothing_and_says_so(self):
        fake = FakeStalwart(
            [account("p1", "platformadmin", ADMIN), account("a1", "alice", ADMIN)]
        )
        output = self.run_main(fake, ["alice"])

        self.assertEqual(output, ["UNCHANGED"])
        self.assertNotIn("x:Account/set", fake.methods())

    def test_accounts_of_another_domain_and_groups_are_left_alone(self):
        fake = FakeStalwart(
            [
                account("p1", "platformadmin", ADMIN),
                account("m2", "mallory", ADMIN, domain="d2"),
                account("g1", "staff", ADMIN, kind="Group"),
            ]
        )
        output = self.run_main(fake, [])

        self.assertEqual(output, ["UNCHANGED"])

    def test_no_administrator_account_on_the_domain_fails_the_run(self):
        fake = FakeStalwart([account("b1", "biber", USER)])

        with self.assertRaises(SystemExit) as raised:
            self.run_main(fake, ["alice"])
        self.assertIn("no account on example.test", str(raised.exception))
        self.assertNotIn("x:Account/set", fake.methods())

    def test_a_refused_update_fails_the_run(self):
        fake = FakeStalwart([account("a1", "alice", USER)], refuse_update=True)

        with self.assertRaises(SystemExit) as raised:
            self.run_main(fake, ["alice"])
        self.assertIn("refused the role change", str(raised.exception))

    def test_a_grant_that_did_not_stick_fails_the_run(self):
        fake = FakeStalwart(
            [account("a1", "alice", USER), account("m1", "mallory", ADMIN)],
            sticky_admin={"m1"},
        )

        with self.assertRaises(SystemExit) as raised:
            self.run_main(fake, ["alice"])
        self.assertIn("mallory still holding it", str(raised.exception))

    def test_transient_errors_are_retried_and_others_fail_at_once(self):
        fake = FakeStalwart([account("a1", "alice", ADMIN)], errors=["rateLimit"])
        self.assertEqual(self.run_main(fake, ["alice"]), ["UNCHANGED"])
        self.assertEqual(self.sleeps, [5])

        fake = FakeStalwart([account("a1", "alice", ADMIN)], errors=["forbidden"])
        with self.assertRaises(SystemExit) as raised:
            self.run_main(fake, ["alice"])
        self.assertIn("refused x:Domain/get", str(raised.exception))

    def test_credentials_travel_on_standard_input_only(self):
        fake = FakeStalwart([account("a1", "alice", ADMIN)])
        self.run_main(fake, ["alice"])

        prefix = ["/usr/bin/container", "exec", "-i", "c1", *CURL.split()]
        for argv, _, _ in fake.calls:
            self.assertEqual(
                argv,
                [
                    *prefix,
                    "-sS",
                    "-f",
                    "-K",
                    "-",
                    "-H",
                    "Content-Type:application/json",
                    URL,
                ],
            )
            self.assertNotIn("recovery-password", " ".join(argv))
        self.assertEqual(set(fake.configs), {"stalwartadmin:recovery-password"})


if __name__ == "__main__":
    unittest.main()
