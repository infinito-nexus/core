from __future__ import annotations

import ast
import io
import json
import re
import tempfile
import unittest
import unittest.mock as mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

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
RETIRED = f"provision {ALIAS}"
ROLES = PROJECT_ROOT / "roles"
CREDENTIALS = ROLES / "web-app-semaphore/files/opentofu/credentials.json"
PROVIDER_SOURCES = {
    "credentials.json": CREDENTIALS,
    "project.py": ROLES / "web-app-semaphore/files/python/project.py",
    "openbao vars": ROLES / "web-app-openbao" / ROLE_FILE_VARS_MAIN,
    "test-provision.js": ROLES / "web-app-semaphore/files/playwright/test-provision.js",
}
SPEC_PROVIDERS = re.compile(r"^const ALL_PROVIDERS = (\[[^\]\n]*\]);$", re.MULTILINE)
PLANTED_PROVIDER = {
    "project.py": ('"proxmox", "scs")', '"proxmox", "scs", "aws")'),
    "openbao vars": (
        "OPENBAO_PROVISION_SECRETS:\n",
        "OPENBAO_PROVISION_SECRETS:\n  aws:\n    platform: []\n    workspace: []\n",
    ),
    "test-provision.js": ('"incus"];', '"incus", "aws"];'),
}


def module_literal(source, name):
    """Args:
        source: a Python module's text.
        name: a module-level constant assigned a literal.

    Returns:
        The value of that literal.
    """
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"the module assigns no {name}")


def provider_tables(paths):
    """Args:
        paths: per name of :data:`PROVIDER_SOURCES`, the file to read.

    Returns:
        Per source, the sorted providers it names: the runner's credentials,
        the templates ``workspace apply`` creates, the provider roles OpenBao
        writes and the providers the Playwright spec probes.
    """
    spec = SPEC_PROVIDERS.search(read_text(str(paths["test-provision.js"])))
    variables = load_yaml_any(str(paths["openbao vars"]))
    return {
        "credentials.json": sorted(
            json.loads(read_text(str(paths["credentials.json"])))["providers"]
        ),
        "project.py": sorted(
            module_literal(read_text(str(paths["project.py"])), "PROVISION_PROVIDERS")
        ),
        "openbao vars": sorted(variables["OPENBAO_PROVISION_SECRETS"]),
        "test-provision.js": sorted(json.loads(spec.group(1))) if spec else [],
    }


def table_findings(tables):
    """Args:
        tables: the result of :func:`provider_tables`.

    Returns:
        One finding per source whose providers differ from ``credentials.json``,
        the one source the runner reads.
    """
    own = tables["credentials.json"]
    return [
        f"{source} names {names}" for source, names in tables.items() if names != own
    ]


class ProviderTableTests(unittest.TestCase):
    def test_every_provider_list_names_the_providers_of_credentials_json(self):
        self.assertEqual(table_findings(provider_tables(PROVIDER_SOURCES)), [])

    def test_negative_control_a_provider_one_copy_adds_is_found(self):
        widened = sorted(
            [*provider_tables(PROVIDER_SOURCES)["credentials.json"], "aws"]
        )
        for source, (old, new) in PLANTED_PROVIDER.items():
            with (
                self.subTest(source=source),
                tempfile.TemporaryDirectory() as directory,
            ):
                paths = {}
                for name, path in PROVIDER_SOURCES.items():
                    target = Path(directory) / path.name
                    text = read_text(str(path))
                    if name == source:
                        self.assertIn(old, text)
                        text = text.replace(old, new, 1)
                    target.write_text(text, encoding="utf-8")
                    paths[name] = target
                self.assertEqual(
                    table_findings(provider_tables(paths)),
                    [f"{source} names {widened}"],
                )


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
        template = self.templates[f"provision-hetzner {ALIAS}"]
        for grant in self.api.perms[(self.project_id, template["id"])]:
            grant["permissions"] |= CAN_MANAGE_PROJECT_RESOURCES
        finding = (
            f"template provision-hetzner {ALIAS} of project {self.project_id} carries "
            f"1 grants, expected one guest grant with {self.mod.GRANT_PERMISSIONS}"
        )
        self.assertEqual(self.deploy(), (1, [finding]))

    def test_negative_control_a_grant_on_a_template_apply_did_not_create_fails(self):
        probe = self.api.call(
            "POST",
            f"/project/{self.project_id}/templates",
            {**self.templates[f"provision-hetzner {ALIAS}"], "name": PROBE, "id": None},
        )
        self.mod.ensure_grant(self.api, self.project_id, probe["id"], "guest", [])
        self.assertEqual(
            self.deploy(),
            (1, [f"template {PROBE} of project {self.project_id} carries a grant"]),
        )

    def plant_retired_template(self):
        retired = self.api.call(
            "POST",
            f"/project/{self.project_id}/templates",
            {**self.templates[f"unlock {ALIAS}"], "name": RETIRED, "id": None},
        )
        self.mod.ensure_grant(self.api, self.project_id, retired["id"], "guest", [])

    def test_a_re_apply_removes_a_template_an_earlier_set_left(self):
        self.plant_retired_template()
        self.mod.run_workspace(self.api, workspace_spec(), lambda seconds: None)
        self.assertNotIn(RETIRED, self.api.templates(self.project_id))
        self.assertEqual(self.deploy(), (0, []))

    def test_negative_control_without_the_prune_the_retired_grant_stays(self):
        self.plant_retired_template()
        with mock.patch.object(
            self.mod, "prune_workspace_templates", lambda *arguments: None
        ):
            self.mod.run_workspace(self.api, workspace_spec(), lambda seconds: None)
        self.assertIn(RETIRED, self.api.templates(self.project_id))
        self.assertEqual(
            self.deploy(),
            (1, [f"template {RETIRED} of project {self.project_id} carries a grant"]),
        )

    def retire_with_a_running_task(self):
        """Returns:
        ``(writes, task)``: the write calls of a re-apply after a retired
        template got a running task, and that task.
        """
        self.plant_retired_template()
        retired = self.api.templates(self.project_id)[RETIRED]
        task = self.api.add_task(self.project_id, retired["id"], "running")
        self.api.writes.clear()
        self.mod.run_workspace(self.api, workspace_spec(), lambda seconds: None)
        stop = f"/project/{self.project_id}/tasks/{task['id']}/stop"
        delete = f"/project/{self.project_id}/templates/{retired['id']}"
        paths = [path for _, path in self.api.writes]
        return [path for path in paths if path in (stop, delete)], task

    def test_a_re_apply_stops_a_retired_template_s_tasks_before_its_delete(self):
        order, task = self.retire_with_a_running_task()
        self.assertEqual(
            order,
            [
                f"/project/{self.project_id}/tasks/{task['id']}/stop",
                f"/project/{self.project_id}/templates/{task['template_id']}",
            ],
        )
        self.assertEqual(task["status"], "stopped")

    def test_negative_control_a_prune_without_the_stop_deletes_a_running_template(
        self,
    ):
        with mock.patch.object(
            self.mod, "stop_tasks", lambda api, templates, changes, sleep: 0
        ):
            order, task = self.retire_with_a_running_task()
        self.assertEqual(
            order, [f"/project/{self.project_id}/templates/{task['template_id']}"]
        )
        self.assertEqual(task["status"], "running")

    def test_one_provision_and_one_destroy_template_per_provider(self):
        names = {entry["name"] for entry in self.mod.PROVISION_TEMPLATES}
        for provider in self.mod.PROVISION_PROVIDERS:
            with self.subTest(provider=provider):
                for action in ("provision", "destroy"):
                    template = self.templates[f"{action}-{provider} {ALIAS}"]
                    self.assertEqual(json.loads(template["arguments"]), [provider])
                    self.assertEqual(template["playbook"], f"{action}.sh")
        self.assertFalse({"provision", "destroy"} & names)

    def test_control_without_the_provision_check_a_wider_grant_passes(self):
        template = self.templates[f"destroy-incus {ALIAS}"]
        for grant in self.api.perms[(self.project_id, template["id"])]:
            grant["permissions"] |= CAN_MANAGE_PROJECT_RESOURCES
        with mock.patch.object(
            self.mod, "provision_grant_findings", lambda *arguments: []
        ):
            self.assertEqual(self.deploy(), (0, []))


if __name__ == "__main__":
    unittest.main()
