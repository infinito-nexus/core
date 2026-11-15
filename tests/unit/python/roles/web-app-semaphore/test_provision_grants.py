from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from .files._semaphore_fake import (
    ALIAS,
    STORE,
    FakeSemaphore,
    load_project,
    platform_spec,
    workspace_spec,
)

PROVISION = "Infinito.Nexus Provision"
CAN_MANAGE_PROJECT_RESOURCES = 4
PROBE = f"tofu version {ALIAS}"


class ProvisionGrantTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)
        self.mod.converge(self.api, platform_spec(), lambda seconds: None)
        self.mod.run_workspace(self.api, workspace_spec(), lambda seconds: None)
        self.project_id = self.api.project_id(PROVISION)
        self.templates = self.api.templates(self.project_id)
        self.store_id = next(
            user["id"]
            for user in self.api.users
            if user["username"] == STORE["username"]
        )

    def deploy(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(self.mod, "Api", lambda url, token, opener: self.api),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = self.mod.main(
                [], io.StringIO(json.dumps(platform_spec())), None, lambda s: None
            )
        return code, [
            line.removeprefix("FINDING ")
            for line in stdout.getvalue().splitlines()
            if line.startswith("FINDING ")
        ]

    def workspace_templates(self):
        return {
            name: template
            for name, template in self.templates.items()
            if name.endswith(f" {ALIAS}")
        }

    def grants(self, template):
        return [
            (grant["role_slug"], grant["permissions"])
            for grant in self.api.perms.get((self.project_id, template["id"]), [])
        ]

    def test_the_provision_project_grants_the_store_run_only(self):
        self.assertEqual(self.deploy(), (0, []))
        admins = {user["id"] for user in self.api.users if user.get("admin")}
        self.assertEqual(
            {
                user_id: role
                for user_id, role in self.api.members[self.project_id].items()
                if user_id not in admins
            },
            {self.store_id: "guest"},
        )
        self.assertEqual(
            sorted(self.workspace_templates()),
            sorted(
                f"{entry['name']} {ALIAS}" for entry in self.mod.PROVISION_TEMPLATES
            ),
        )
        run_and_read = self.mod.CAN_RUN_PROJECT_TASKS | self.mod.CAN_READ_PROJECT
        for name, template in self.workspace_templates().items():
            with self.subTest(name):
                self.assertEqual(self.grants(template), [("guest", run_and_read)])

    def test_negative_control_a_second_member_fails(self):
        self.api.users.append({"id": 999, "username": "intruder", "admin": False})
        self.api.members[self.project_id][999] = "guest"
        self.assertEqual(
            self.deploy(),
            (1, [f"account 999 holds guest in project {self.project_id}"]),
        )

    def test_negative_control_a_grant_with_another_bit_fails(self):
        template = self.templates[f"provision {ALIAS}"]
        for grant in self.api.perms[(self.project_id, template["id"])]:
            grant["permissions"] |= CAN_MANAGE_PROJECT_RESOURCES
        finding = (
            f"template provision {ALIAS} of project {self.project_id} carries "
            f"1 grants, expected one guest grant with {self.mod.GRANT_PERMISSIONS}"
        )
        self.assertEqual(self.deploy(), (1, [finding]))

    def test_negative_control_a_grant_on_a_template_apply_did_not_create_fails(self):
        probe = self.api.call(
            "POST",
            f"/project/{self.project_id}/templates",
            {**self.templates[f"provision {ALIAS}"], "name": PROBE, "id": None},
        )
        self.mod.ensure_grant(self.api, self.project_id, probe["id"], "guest", [])
        self.assertEqual(
            self.deploy(),
            (1, [f"template {PROBE} of project {self.project_id} carries a grant"]),
        )

    def test_control_without_the_provision_check_a_wider_grant_passes(self):
        template = self.templates[f"destroy {ALIAS}"]
        for grant in self.api.perms[(self.project_id, template["id"])]:
            grant["permissions"] |= CAN_MANAGE_PROJECT_RESOURCES
        with mock.patch.object(
            self.mod, "provision_grant_findings", lambda *arguments: []
        ):
            self.assertEqual(self.deploy(), (0, []))


if __name__ == "__main__":
    unittest.main()
