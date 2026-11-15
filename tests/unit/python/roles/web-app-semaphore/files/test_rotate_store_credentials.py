from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest import mock

from tests.utils.openbao_stub import OpenBaoStub
from utils.openbao_client import OpenBaoClient

from ._semaphore_fake import PYTHON_DIR, FakeSemaphore, load_project, platform_spec

TOKEN = "s.rotation-task-token"
NOW = datetime(2026, 11, 13, 9, 0, 0, tzinfo=UTC)
EXPIRES_AT = "2026-11-27T09:00:00+00:00"
GITEA_TOKEN = "g" * 40
SEMAPHORE_TOKEN = "5" * 44
STORE = "store"
WORKSPACES = "Infinito.Nexus Workspaces"
ROTATION = "rotate store credentials"


def load_rotation():
    """Returns:
    The module ``files/python/rotate_store_credentials.py``.
    """
    spec = spec_from_file_location(
        "rotate_store_credentials", str(PYTHON_DIR / "rotate_store_credentials.py")
    )
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeCursor:
    def __init__(self, database):
        self.database = database
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.database.statements.append(sql.split(" ", 1)[0])
        if sql.startswith("INSERT"):
            token, refused_after, name, username = params
            user = self.database.users.get(username)
            if user is None or user["admin"]:
                self.rows = []
                return
            self.database.tokens.append(
                {
                    "id": token,
                    "user": username,
                    "name": name,
                    "expires_at": refused_after,
                }
            )
            self.rows = [(user["id"],)]
        elif sql.startswith("SELECT"):
            self.rows = [
                (t["name"],) for t in self.database.tokens if t["user"] == params[0]
            ]
        else:
            username, names = params
            self.database.tokens = [
                t
                for t in self.database.tokens
                if not (t["user"] == username and t["name"] in names)
            ]

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeDatabase:
    """The ``user`` and ``user__token`` tables of Semaphore, as far as the rotation reads them."""

    def __init__(self, tokens=()):
        self.users = {
            STORE: {"id": 7, "admin": False},
            "breakglass-admin": {"id": 1, "admin": True},
        }
        self.tokens = [
            {"id": f"t{index}", "user": user, "name": name, "expires_at": None}
            for index, (user, name) in enumerate(tokens)
        ]
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return FakeCursor(self)

    def names(self, user=STORE):
        return sorted(t["name"] for t in self.tokens if t["user"] == user)


class RotationCase(unittest.TestCase):
    def setUp(self):
        self.mod = load_rotation()
        self.stub = OpenBaoStub(
            tokens={TOKEN: ["platform/store/semaphore", "platform/store/gitea"]},
            logins={},
        )
        self.addCleanup(self.stub.close)
        self.client = OpenBaoClient(self.stub.addr, self.stub.cafile, TOKEN)
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.database = FakeDatabase()

    def plan(self, now=NOW):
        spec = self.mod.plan(now, self.scratch.name)
        Path(spec["gitea_store_token_file"]).write_text(
            GITEA_TOKEN + "\n", encoding="utf-8"
        )
        return spec

    def rotate(self, now=NOW, token=SEMAPHORE_TOKEN):
        return self.mod.rotate(
            self.plan(now), self.client, self.database, STORE, lambda size: token
        )

    def entries(self, kind):
        return self.stub.kv.get(f"platform/store/{kind}", [])


class TestTheRotationEntries(RotationCase):
    def test_the_rotation_writes_token_and_expires_at(self):
        lines = self.rotate()
        for kind, token in (("gitea", GITEA_TOKEN), ("semaphore", SEMAPHORE_TOKEN)):
            with self.subTest(kind=kind):
                written = self.entries(kind)
                self.assertEqual(written, [{"token": token, "expires_at": EXPIRES_AT}])
                moment = datetime.fromisoformat(written[0]["expires_at"])
                self.assertEqual(moment.utcoffset(), timedelta(0))
                self.assertEqual(moment - NOW, timedelta(days=14))
        for line in lines:
            self.assertNotIn(GITEA_TOKEN, line)
            self.assertNotIn(SEMAPHORE_TOKEN, line)

    def test_the_gitea_handover_file_is_gone_after_the_run(self):
        spec = self.plan()
        self.mod.rotate(
            spec, self.client, self.database, STORE, lambda size: SEMAPHORE_TOKEN
        )
        self.assertFalse(Path(spec["gitea_store_token_file"]).exists())

    def test_control_a_planted_third_field_fails(self):
        planted = lambda token, expires_at: {  # noqa: E731
            "token": token,
            "expires_at": expires_at,
            "minted_by": "rotation",
        }
        with (
            mock.patch.object(self.mod, "entry", planted),
            self.assertRaisesRegex(self.mod.RotationError, "holds the fields"),
        ):
            self.rotate()
        self.assertEqual((self.entries("gitea"), self.entries("semaphore")), ([], []))

    def test_control_an_expires_at_without_an_offset_fails(self):
        for bare in ("2026-11-27T09:00:00", "2026-11-27T09:00:00Z", "2026-11-27"):
            with self.subTest(expires_at=bare):
                planted = lambda token, expires_at, bare=bare: {  # noqa: E731
                    "token": token,
                    "expires_at": bare,
                }
                with (
                    mock.patch.object(self.mod, "entry", planted),
                    self.assertRaisesRegex(self.mod.RotationError, "numeric offset"),
                ):
                    self.rotate()
                self.assertEqual(self.entries("gitea"), [])

    def test_negative_control_without_the_field_check_a_third_field_is_written(self):
        planted = lambda token, expires_at: {  # noqa: E731
            "token": token,
            "expires_at": expires_at,
            "minted_by": "rotation",
        }
        with (
            mock.patch.object(self.mod, "entry", planted),
            mock.patch.object(self.mod, "entry_findings", lambda candidate: []),
        ):
            self.rotate()
        self.assertIn("minted_by", self.entries("gitea")[0])

    def test_a_short_or_missing_token_is_never_written(self):
        with self.assertRaisesRegex(self.mod.RotationError, "no token of at least 40"):
            self.rotate(token="short")
        self.assertEqual(self.entries("semaphore"), [])
        self.assertEqual(self.database.tokens, [])

    def test_a_doctored_plan_is_refused_before_any_write(self):
        spec = self.plan()
        spec["gitea_store_token_expires_at"] = "2027-11-27T09:00:00+00:00"
        with self.assertRaisesRegex(self.mod.RotationError, "14 days later"):
            self.mod.rotate(
                spec, self.client, self.database, STORE, lambda size: SEMAPHORE_TOKEN
            )
        self.assertEqual((self.entries("gitea"), self.database.tokens), ([], []))

    def test_the_task_token_writes_no_other_path(self):
        with self.assertRaisesRegex(Exception, "HTTP 403"):
            self.client.write(
                "platform", "store/directory/ws-0a", {"token": GITEA_TOKEN}
            )


class TestTheSemaphoreToken(RotationCase):
    def test_the_token_is_named_after_its_expires_at_and_semaphore_refuses_it_after_30_days(
        self,
    ):
        self.rotate()
        minted = next(t for t in self.database.tokens if t["id"] == SEMAPHORE_TOKEN)
        self.assertEqual(minted["name"], f"store-{EXPIRES_AT}")
        self.assertEqual(minted["user"], STORE)
        self.assertEqual(minted["expires_at"] - NOW, timedelta(days=30))

    def test_each_run_revokes_every_store_token_whose_expires_at_passed_and_no_other(
        self,
    ):
        self.database = FakeDatabase(
            tokens=(
                (STORE, "store-2026-11-12T09:00:00+00:00"),
                (STORE, "store-2026-11-13T08:59:59+00:00"),
                (STORE, "store-2026-11-20T09:00:00+00:00"),
                (STORE, "store-2026-11-12T09:00:00"),
                (STORE, "manual"),
                ("breakglass-admin", "store-2026-11-01T09:00:00+00:00"),
            )
        )
        lines = self.rotate()
        self.assertEqual(
            self.database.names(),
            sorted(
                [
                    "manual",
                    "store-2026-11-12T09:00:00",
                    "store-2026-11-20T09:00:00+00:00",
                    f"store-{EXPIRES_AT}",
                ]
            ),
        )
        self.assertEqual(
            self.database.names("breakglass-admin"), ["store-2026-11-01T09:00:00+00:00"]
        )
        self.assertIn("revoked semaphore token store-2026-11-12T09:00:00+00:00", lines)

    def test_a_manual_run_keeps_every_token_whose_expires_at_lies_ahead(self):
        self.rotate()
        self.rotate(now=NOW + timedelta(hours=1), token="6" * 44)
        self.assertEqual(
            self.database.names(),
            [f"store-{EXPIRES_AT}", "store-2026-11-27T10:00:00+00:00"],
        )
        self.rotate(now=NOW + timedelta(days=14, seconds=1), token="7" * 44)
        self.assertEqual(
            self.database.names(),
            ["store-2026-11-27T10:00:00+00:00", "store-2026-12-11T09:00:01+00:00"],
        )

    def test_negative_control_revoking_by_prefix_alone_drops_a_live_token(self):
        self.rotate()
        with mock.patch.object(
            self.mod,
            "expired_names",
            lambda names, now: sorted(n for n in names if n.startswith("store-")),
        ):
            self.rotate(now=NOW + timedelta(hours=1), token="6" * 44)
        self.assertEqual(self.database.names(), [])

    def test_an_admin_store_account_gets_no_token(self):
        self.database.users[STORE]["admin"] = True
        with self.assertRaisesRegex(self.mod.RotationError, "missing or an admin"):
            self.rotate()
        self.assertEqual(self.entries("semaphore"), [])


class TestTheCommandLine(unittest.TestCase):
    def setUp(self):
        self.mod = load_rotation()

    def test_plan_prints_the_extra_variables_of_the_playbook(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = self.mod.main(["plan", "/tmp/task"], {}, lambda: NOW)
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "gitea_store_token_now": "2026-11-13T09:00:00+00:00",
                "gitea_store_token_expires_at": EXPIRES_AT,
                "gitea_store_token_file": "/tmp/task/gitea-token",
            },
        )

    def test_an_unknown_command_is_refused(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = self.mod.main(["mint", "x"], {}, lambda: NOW)
        self.assertEqual(code, 2)
        self.assertIn(
            "expects plan <task directory> or rotate <plan file>", stderr.getvalue()
        )


class TestTheRotationTemplate(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)
        self.changes, self.findings = self.mod.converge(
            self.api, platform_spec(), lambda seconds: None
        )
        self.project_id = self.api.project_id(WORKSPACES)
        self.template = self.api.templates(self.project_id)[ROTATION]

    def rotation_schedules(self):
        """Returns:
        The schedules of the rotation template; the prune template keeps
        its own.
        """
        return [
            s
            for s in self.api.schedules(self.project_id)
            if s["template_id"] == self.template["id"]
        ]

    def test_the_template_runs_the_rotation_script_on_the_platform_inventory(self):
        self.assertEqual(self.template["app"], "infinito-script")
        self.assertEqual(self.template["playbook"], "store-credentials.sh")
        self.assertEqual(json.loads(self.template["arguments"]), [])
        self.assertEqual(self.template["survey_vars"], [])
        self.assertEqual(self.template["runner_tag"], "workspaces")
        repositories = {
            r["id"]: r["name"]
            for r in self.api.objects[(self.project_id, "repositories")]
        }
        self.assertEqual(repositories[self.template["repository_id"]], "inventory")
        self.assertEqual(self.mod.lock_findings(self.template), [])

    def test_the_template_runs_every_7_days(self):
        self.assertEqual(
            [
                (s["template_id"], s["cron_format"], s["active"])
                for s in self.rotation_schedules()
            ],
            [(self.template["id"], "0 4 * * 1", True)],
        )

    def test_the_store_holds_no_grant_on_it(self):
        self.assertEqual(
            self.api.perms.get((self.project_id, self.template["id"]), []), []
        )
        self.assertEqual(self.findings, [])

    def test_negative_control_a_planted_grant_is_a_finding(self):
        self.mod.ensure_grant(
            self.api, self.project_id, self.template["id"], "guest", []
        )
        findings = self.mod.grant_findings(
            self.api,
            self.project_id,
            [e["name"] for e in self.mod.WORKSPACES_TEMPLATES],
            "guest",
        )
        self.assertEqual(
            findings,
            [f"template {ROTATION} of project {self.project_id} carries a grant"],
        )

    def test_a_second_converge_writes_nothing(self):
        self.assertEqual(
            self.mod.converge(self.api, platform_spec(), lambda s: None)[0], []
        )

    def test_a_hand_changed_or_doubled_schedule_is_set_back(self):
        path = f"/project/{self.project_id}/schedules"
        held = self.rotation_schedules()[0]
        self.api.call(
            "PUT",
            f"{path}/{held['id']}",
            {**held, "cron_format": "* * * * *", "active": False},
        )
        self.api.call("POST", path, {**held, "id": None})
        self.mod.converge(self.api, platform_spec(), lambda s: None)
        self.assertEqual(
            [(s["cron_format"], s["active"]) for s in self.rotation_schedules()],
            [("0 4 * * 1", True)],
        )

    def test_the_rotation_identity_names_the_template(self):
        stdout = io.StringIO()
        spec = {
            "url": "http://semaphore",
            "token": "t",
            "workspaces": {"project": WORKSPACES},
        }
        with (
            mock.patch.object(self.mod, "Api", lambda url, token, opener: self.api),
            redirect_stdout(stdout),
        ):
            code = self.mod.main(
                [self.mod.ROTATION_COMMAND],
                io.StringIO(json.dumps(spec)),
                None,
                lambda s: None,
            )
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"project_id": self.project_id, "template_id": self.template["id"]},
        )

    def test_negative_control_a_missing_rotation_template_is_refused(self):
        self.api.call(
            "DELETE", f"/project/{self.project_id}/templates/{self.template['id']}"
        )
        self.assertEqual(self.rotation_schedules(), [])
        with self.assertRaisesRegex(
            self.mod.ApiError, f"0 templates .* named {ROTATION}"
        ):
            self.mod.store_rotation_identity(self.api, WORKSPACES)


if __name__ == "__main__":
    unittest.main()
