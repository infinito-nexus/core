from __future__ import annotations

import unittest

from tests.utils.openbao_stub import OpenBaoStub

from .test_workspace_sh import ScriptCase

FIXTURE_ROLE = "workspace-fixture"
WORKSPACE_JWT = "eyJ.workspace-task.sig"
MEMBERS_JWT = "eyJ.members-task.sig"
FIXTURE_TOKEN = "s.fixture-reader"
MEMBERS_TOKEN = "s.members-reader"
VALUE = "known-platform-password-4711"
HOST_VARS = """users:
  platform_administrator:
    password:
      openbao: platform/fixture/platform/users/platform_administrator#password
"""


class WorkspacePreflightTests(ScriptCase, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stub = OpenBaoStub(
            tokens={
                FIXTURE_TOKEN: ["platform/fixture/"],
                MEMBERS_TOKEN: ["platform/store/invites/"],
            },
            logins={
                (FIXTURE_ROLE, WORKSPACE_JWT): FIXTURE_TOKEN,
                ("members", WORKSPACE_JWT): MEMBERS_TOKEN,
            },
        )
        cls.stub.put(
            "platform/fixture/platform/users/platform_administrator",
            {"password": VALUE},
        )
        cls.addClassCleanup(cls.stub.close)

    def setUp(self):
        super().setUp()
        host_vars = self.checkout / "host_vars"
        host_vars.mkdir()
        (host_vars / "platform.yml").write_text(HOST_VARS, encoding="utf-8")
        self.logins = self.stub.login_count

    def login_env(self, **overrides):
        env = {
            "BAO_ADDR": self.stub.addr,
            "BAO_CACERT": self.stub.cafile,
            "BAO_ROLE": "members",
            "BAO_FIXTURE_ROLE": FIXTURE_ROLE,
            "SEMAPHORE_JWT": WORKSPACE_JWT,
        }
        env.update(overrides)
        return {key: value for key, value in env.items() if value is not None}

    def test_workspace_sh_logs_in_before_the_playbook(self):
        run = self.run_script(self.login_env())
        self.assertTrue(self.record.exists(), run.stderr)
        self.assertNotIn("bao/preflight.py", run.stderr)
        self.assertEqual(self.stub.login_count, self.logins + 1)
        self.assertEqual(self.recorded()["bao_token"], FIXTURE_TOKEN)
        self.assertNotIn(VALUE, run.stdout + run.stderr)

    def test_without_a_login_workspace_sh_stops_before_the_playbook(self):
        run = self.run_script(self.login_env(SEMAPHORE_JWT=None))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("no OpenBao login", run.stderr)
        self.assertFalse(self.record.exists(), "the playbook ran")

    def test_negative_control_a_jwt_of_another_template_is_refused(self):
        run = self.run_script(self.login_env(SEMAPHORE_JWT=MEMBERS_JWT))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(f"role {FIXTURE_ROLE}", run.stderr)
        self.assertFalse(self.record.exists(), "the playbook ran")

    def test_negative_control_without_the_fixture_role_no_login_takes_place(self):
        run = self.run_script(self.login_env(BAO_FIXTURE_ROLE=""))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("no OpenBao login", run.stderr)
        self.assertEqual(self.stub.login_count, self.logins)
        self.assertFalse(self.record.exists(), "the playbook ran with the members role")

    def test_a_denied_reference_stops_before_the_playbook(self):
        (self.checkout / "host_vars" / "platform.yml").write_text(
            HOST_VARS.replace("platform/fixture/", "platform/store/"),
            encoding="utf-8",
        )
        run = self.run_script(self.login_env())
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("users.platform_administrator.password", run.stderr)
        self.assertFalse(self.record.exists(), "the playbook ran")

    def test_negative_control_a_reference_in_another_users_field_is_refused(self):
        (self.checkout / "host_vars" / "platform.yml").write_text(
            HOST_VARS.replace("    password:", "    username:"), encoding="utf-8"
        )
        run = self.run_script(self.login_env())
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("users.platform_administrator.username", run.stderr)
        self.assertEqual(self.stub.login_count, self.logins)
        self.assertFalse(self.record.exists(), "the playbook ran")

    def test_an_inventory_without_references_runs_without_a_login(self):
        (self.checkout / "host_vars" / "platform.yml").write_text(
            "users: {}\n", encoding="utf-8"
        )
        run = self.run_script(self.login_env())
        self.assertTrue(self.record.exists(), run.stderr)
        self.assertNotIn("bao/preflight.py", run.stderr)
        self.assertEqual(self.stub.login_count, self.logins)
        self.assertIsNone(self.recorded()["bao_token"])


if __name__ == "__main__":
    unittest.main()
