from __future__ import annotations

import unittest

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from .files._semaphore_fake import (
    ALIAS,
    WORKSPACE_ID,
    FakeSemaphore,
    decoded,
    load_project,
    platform_spec,
    workspace_spec,
)

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
OPENBAO_ROLES = (
    PROJECT_ROOT / "roles/web-app-openbao/templates/workspace/jwt_roles.json.j2"
)
LOGIN = ("BAO_ADDR", "BAO_CACERT", "BAO_ROLE")
ADDR = "https://openbao.example.org"
CACERT = "/etc/ssl/certs/selfsigned.crt"


def workspace_environment():
    """Returns:
    The plain variables ``tasks/utils/workspace/operation.yml`` hands
    ``project.py`` for the workspace project, each still its expression.
    """
    tasks = load_yaml_str(
        read_text(str(ROLE / "tasks" / "utils" / "workspace" / "operation.yml"))
    )
    task = next(t for t in tasks if "semaphore_workspace_spec" in t.get("vars", {}))
    return task["vars"]["semaphore_workspace_spec"]["environment"]


def login_findings(environment, variables, alias):
    """Args:
    environment: the workspace environment of :func:`workspace_environment`.
    variables: ``SEMAPHORE_WORKSPACES_VARIABLES`` with rendered values.
    alias: ``semaphore_workspace_alias``.

    Returns:
        One finding per task token login variable the workspace environment
        does not take from the Workspaces environment or the workspace alias.
    """
    renderer = NativeEnvironment(undefined=StrictUndefined)
    expected = {**{k: variables[k] for k in LOGIN[:2]}, "BAO_ROLE": alias}
    findings = []
    for name in LOGIN:
        if name not in environment:
            findings.append(f"{name} is not set")
            continue
        value = renderer.from_string(environment[name]).render(
            SEMAPHORE_WORKSPACES_VARIABLES=variables, semaphore_workspace_alias=alias
        )
        if value != expected[name]:
            findings.append(f"{name} is {value!r}, expected {expected[name]!r}")
    return findings


class TestWorkspaceTaskLogin(unittest.TestCase):
    def setUp(self):
        self.vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.variables = {"BAO_ADDR": ADDR, "BAO_CACERT": CACERT}

    def test_the_workspace_project_logs_in_to_its_own_role(self):
        self.assertEqual(
            login_findings(workspace_environment(), self.variables, ALIAS), []
        )

    def test_the_login_reuses_the_workspaces_sources(self):
        workspaces = self.vars["SEMAPHORE_WORKSPACES_VARIABLES"]
        self.assertEqual(
            workspaces["BAO_CACERT"], "{{ CA_TRUST_CERT_CONTAINER_SELFSIGNED }}"
        )
        self.assertEqual(self.vars["SEMAPHORE_WORKSPACE_ALIAS"], "ws-{{ WORKSPACE }}")
        self.assertIn(
            "{% set openbao_workspace = 'ws-' ~ WORKSPACE %}",
            read_text(str(OPENBAO_ROLES)),
        )

    def test_negative_control_a_dropped_or_foreign_role_is_reported(self):
        environment = {
            k: v for k, v in workspace_environment().items() if k != "BAO_ROLE"
        }
        self.assertEqual(
            login_findings(environment, self.variables, ALIAS),
            ["BAO_ROLE is not set"],
        )
        environment["BAO_ROLE"] = "members"
        self.assertEqual(
            login_findings(environment, self.variables, ALIAS),
            [f"BAO_ROLE is 'members', expected {ALIAS!r}"],
        )

    def test_project_py_writes_the_login_into_the_workspace_project(self):
        mod = load_project()
        api = FakeSemaphore(mod.ApiError)
        mod.converge(api, platform_spec(), lambda seconds: None)
        spec = workspace_spec()
        spec["environment"].update(
            {"BAO_ADDR": ADDR, "BAO_CACERT": CACERT, "BAO_ROLE": ALIAS}
        )
        result = mod.run_workspace(api, spec, lambda seconds: None)[1]["result"]
        project_id = result["project_id"]
        template = api.templates(project_id)["deploy"]
        environment = api.call(
            "GET", f"/project/{project_id}/environment/{template['environment_id']}"
        )
        self.assertEqual(
            {k: decoded(environment).get(k) for k in (*LOGIN, "WORKSPACE")},
            {
                "BAO_ADDR": ADDR,
                "BAO_CACERT": CACERT,
                "BAO_ROLE": ALIAS,
                "WORKSPACE": WORKSPACE_ID,
            },
        )


if __name__ == "__main__":
    unittest.main()
