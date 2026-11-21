from __future__ import annotations

import io
import json
import unittest
import unittest.mock as mock
from contextlib import ExitStack, redirect_stderr, redirect_stdout

from .files._semaphore_fake import (
    FakeSemaphore,
    load_project,
    platform_spec,
    workspaces_spec,
)

CAN_RUN_PROJECT_TASKS = 1
CAN_MANAGE_PROJECT_RESOURCES = 4
CAN_READ_PROJECT = 128
RUN_AND_READ = CAN_RUN_PROJECT_TASKS | CAN_READ_PROJECT
STARTED = ("members", "user", "workspace")
ROTATION = "rotate store credentials"


class StoreGrantTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)
        self.mod.converge(self.api, platform_spec(), lambda seconds: None)
        self.project_id = self.api.project_id(workspaces_spec()["project"])
        self.templates = self.api.templates(self.project_id)

    def deploy(self, *patches):
        """Args:
        patches: ``(name, value)`` pairs patched into the converger.

        Returns:
            The exit code and the stdout lines of a full deploy converge.
        """
        stdout = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(self.mod, "Api", lambda url, token, opener: self.api)
            )
            for name, value in patches:
                stack.enter_context(mock.patch.object(self.mod, name, value))
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(io.StringIO()))
            code = self.mod.main(
                [], io.StringIO(json.dumps(platform_spec())), None, lambda s: None
            )
        return code, stdout.getvalue().splitlines()

    def grants(self, name):
        return [
            (grant["role_slug"], grant["permissions"])
            for grant in self.api.perms.get(
                (self.project_id, self.templates[name]["id"]), []
            )
        ]

    def plant(self, name, permissions):
        self.api.call(
            "POST",
            f"/project/{self.project_id}/templates/{self.templates[name]['id']}/perms",
            {"role_slug": "guest", "permissions": permissions},
        )

    def test_the_workspaces_project_grants_the_store_three_templates(self):
        self.assertIn(ROTATION, self.templates)
        for name in sorted(self.templates):
            with self.subTest(name):
                expected = [("guest", RUN_AND_READ)] if name in STARTED else []
                self.assertEqual(self.grants(name), expected)
        code, lines = self.deploy()
        self.assertEqual(code, 0, lines)
        self.assertEqual([line for line in lines if line.startswith("FINDING")], [])

    def test_negative_control_a_grant_with_another_bit_fails_the_deploy(self):
        grant = self.api.perms[(self.project_id, self.templates["members"]["id"])][0]
        grant["permissions"] = RUN_AND_READ | CAN_MANAGE_PROJECT_RESOURCES
        code, lines = self.deploy(("ensure_grant", lambda *arguments: None))
        self.assertEqual(code, 1)
        self.assertIn(
            f"FINDING template members of project {self.project_id} carries 1 grants, "
            f"expected one guest grant with {RUN_AND_READ}",
            lines,
        )

    def test_negative_control_a_grant_on_a_fourth_template_fails_the_deploy(self):
        self.plant(ROTATION, RUN_AND_READ)
        code, lines = self.deploy()
        self.assertEqual(code, 1)
        self.assertIn(
            f"FINDING template {ROTATION} of project {self.project_id} carries a grant",
            lines,
        )

    def test_control_without_the_query_both_planted_grants_pass(self):
        self.plant(ROTATION, RUN_AND_READ)
        grant = self.api.perms[(self.project_id, self.templates["members"]["id"])][0]
        grant["permissions"] = RUN_AND_READ | CAN_MANAGE_PROJECT_RESOURCES
        code, lines = self.deploy(
            ("ensure_grant", lambda *arguments: None),
            ("grant_findings", lambda *arguments: []),
        )
        self.assertEqual(code, 0, lines)


if __name__ == "__main__":
    unittest.main()
