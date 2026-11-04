import contextlib
import io
import json
import os
import subprocess
import tempfile
import types
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-peertube"
SCRIPT = ROLE / "files" / "python" / "rbac_sync.py"
SQL_DIR = ROLE / "files" / "sql" / "rbac"
SQL_FILES = (
    "select-members-without-account.sql",
    "link-preprovisioned-accounts.sql",
    "reconcile-roles.sql",
)
ROLE_IDS = {"administrator": 0, "moderator": 1, "user": 2}


def load_module():
    module = types.ModuleType("peertube_rbac_sync")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


def member(username, email):
    return {"username": username, "email": email, "name": ""}


class FakeDatabase:
    def __init__(self, missing, reconcile_output):
        self.missing = missing
        self.reconcile_output = reconcile_output
        self.runs = []

    def __call__(self, argv, **kwargs):
        script = kwargs["input"]
        forwarded = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-e"]
        self.runs.append((script, forwarded, kwargs["env"]))
        if "PEERTUBE_RBAC_RANKED" in script:
            stdout = json.dumps(self.missing) + "\n"
        elif "PEERTUBE_RBAC_CREATED" in script:
            stdout = "\n".join(m["username"] for m in self.missing) + "\n"
        else:
            stdout = self.reconcile_output
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePeertube:
    def __init__(self, conflicts=()):
        self.requests = []
        self.conflicts = set(conflicts)

    def __call__(self, request, timeout):
        body = request.data.decode() if request.data else ""
        self.requests.append((request.full_url, dict(request.header_items()), body))
        if request.full_url.endswith("/oauth-clients/local"):
            return FakeResponse(
                json.dumps({"client_id": "cid", "client_secret": "cs"}).encode()
            )
        if request.full_url.endswith("/users/token"):
            return FakeResponse(json.dumps({"access_token": "tok"}).encode())
        created = json.loads(body)
        if created["username"] in self.conflicts:
            raise urllib.error.HTTPError(request.full_url, 409, "Conflict", {}, None)
        return FakeResponse(json.dumps({"user": {"id": 7}}).encode())


class PeertubeRbacSyncTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.workdir = tempfile.TemporaryDirectory()
        for name in SQL_FILES:
            (Path(self.workdir.name) / name).write_text(
                read_text(str(SQL_DIR / name)), encoding="utf-8"
            )
        self.previous = Path.cwd()
        os.chdir(self.workdir.name)

    def tearDown(self):
        os.chdir(self.previous)
        self.workdir.cleanup()

    def environ(self, members):
        return {
            "RBAC_SYNC_CONTAINER_BIN": "/usr/bin/container",
            "RBAC_SYNC_CID": "db1",
            "PGPASSWORD": "pg-secret",
            "PEERTUBE_DB_USER": "peertube",
            "PEERTUBE_DB_NAME": "peertube",
            "PEERTUBE_URL": "http://127.0.0.1:9000",
            "PEERTUBE_HOSTNAME": "video.example.org",
            "PEERTUBE_ROOT_USERNAME": "root",
            "PEERTUBE_ROOT_PASSWORD": "root-secret",
            "PEERTUBE_RBAC_ROLE_IDS": json.dumps(ROLE_IDS),
            "PEERTUBE_OIDC_PLUGIN": "peertube-plugin-auth-openid-connect",
            "RBAC_MEMBERS": json.dumps(members),
        }

    def run_main(self, members, database, peertube):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(self.environ(members), run=database, opener=peertube)
        return stdout.getvalue().strip().splitlines()

    def test_missing_members_are_created_as_root_and_linked_to_the_plugin(self):
        members = {
            "administrator": [
                member("alice", "alice@example.org"),
                member("noemail", ""),
            ],
            "moderator": [
                member("alice", "alice@example.org"),
                member("bob", "bob@example.org"),
            ],
        }
        missing = [
            {"username": "alice", "email": "alice@example.org", "role": 0},
            {"username": "bob", "email": "bob@example.org", "role": 1},
        ]
        database = FakeDatabase(missing, "CHANGED bob role=1\n")
        peertube = FakePeertube()

        output = self.run_main(members, database, peertube)

        ranked = json.loads(database.runs[0][2]["PEERTUBE_RBAC_RANKED"])
        self.assertEqual(ranked, missing)
        self.assertEqual(
            [url for url, _, _ in peertube.requests],
            [
                "http://127.0.0.1:9000/api/v1/oauth-clients/local",
                "http://127.0.0.1:9000/api/v1/users/token",
                "http://127.0.0.1:9000/api/v1/users",
                "http://127.0.0.1:9000/api/v1/users",
            ],
        )
        token_form = urllib.parse.parse_qs(peertube.requests[1][2])
        self.assertEqual(token_form["username"], ["root"])
        self.assertEqual(token_form["password"], ["root-secret"])
        created = [json.loads(body) for _, _, body in peertube.requests[2:]]
        self.assertEqual(
            [(c["username"], c["role"]) for c in created], [("alice", 0), ("bob", 1)]
        )
        self.assertTrue(all(len(c["password"]) == 48 for c in created))
        self.assertEqual(peertube.requests[2][1]["Authorization"], "Bearer tok")
        self.assertEqual(peertube.requests[2][1]["Host"], "video.example.org")
        self.assertEqual(
            json.loads(database.runs[1][2]["PEERTUBE_RBAC_CREATED"]),
            ["alice@example.org", "bob@example.org"],
        )
        self.assertEqual(
            output,
            ["CHANGED alice created", "CHANGED bob created", "CHANGED bob role=1"],
        )

    def test_nothing_missing_touches_no_api_and_reports_the_reconcile(self):
        database = FakeDatabase([], "UNCHANGED\n")
        peertube = FakePeertube()

        output = self.run_main(
            {"administrator": [member("alice", "alice@example.org")], "moderator": []},
            database,
            peertube,
        )

        self.assertEqual(peertube.requests, [])
        self.assertEqual(len(database.runs), 2)
        self.assertEqual(output, ["UNCHANGED"])

    def test_an_account_created_meanwhile_is_not_an_error(self):
        missing = [{"username": "alice", "email": "alice@example.org", "role": 0}]
        database = FakeDatabase(missing, "UNCHANGED\n")

        output = self.run_main(
            {"administrator": [member("alice", "alice@example.org")], "moderator": []},
            database,
            FakePeertube(conflicts={"alice"}),
        )

        self.assertEqual(output, ["CHANGED alice created"])

    def test_each_sql_run_forwards_only_the_variables_it_reads(self):
        missing = [{"username": "bob", "email": "bob@example.org", "role": 1}]
        database = FakeDatabase(missing, "UNCHANGED\n")

        self.run_main(
            {"administrator": [], "moderator": [member("bob", "bob@example.org")]},
            database,
            FakePeertube(),
        )

        self.assertEqual(
            [forwarded for _, forwarded, _ in database.runs],
            [
                ["PGPASSWORD", "PEERTUBE_RBAC_RANKED"],
                [
                    "PGPASSWORD",
                    "PEERTUBE_OIDC_PLUGIN",
                    "PEERTUBE_ROOT_USERNAME",
                    "PEERTUBE_RBAC_CREATED",
                ],
                [
                    "PGPASSWORD",
                    "RBAC_MEMBERS",
                    "PEERTUBE_RBAC_ROLE_IDS",
                    "PEERTUBE_OIDC_PLUGIN",
                ],
            ],
        )
        for script, forwarded, _ in database.runs:
            read = {
                line.split()[2]
                for line in script.splitlines()
                if line.startswith("\\getenv")
            }
            self.assertTrue(
                read <= set(forwarded), f"{read - set(forwarded)} not forwarded"
            )


if __name__ == "__main__":
    unittest.main()
