from __future__ import annotations

import json
import re
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
SYNC = ROLE / "tasks" / "utils" / "project" / "sync.yml"
SCRIPTS = ("members.sh", "user.sh")
HEADER = re.compile(r"# Env of the Workspaces project:\n((?:#.*\n)+)")
NAME = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
RUNTIME = {"SEMAPHORE_JWT", "INFINITO_SRC_DIR"}
SECRETS = {"KC_CLIENT_SECRET", "SEMAPHORE_DB_PASS"}


def needed():
    """Returns:
    Every variable the Workspaces scripts name as coming from the project
    environment, without the ones Semaphore or the runner image set.
    """
    names = set()
    for script in SCRIPTS:
        text = read_text(str(ROLE / "files" / "shell" / "repository" / script))
        match = HEADER.search(text)
        assert match is not None, f"{script} lost its environment header"
        names |= set(NAME.findall(match.group(1)))
    return names - RUNTIME


def environment_findings(variables, secrets):
    """Args:
    variables: ``SEMAPHORE_WORKSPACES_VARIABLES``.
    secrets: ``SEMAPHORE_WORKSPACES_SECRETS``.

    Returns:
        Every needed variable the environment lacks and every secret it
        carries as a plain variable.
    """
    findings = [
        f"{name} is not set"
        for name in sorted(needed() - set(variables) - set(secrets))
    ]
    findings += [
        f"{name} is a plain variable" for name in sorted(SECRETS & set(variables))
    ]
    findings += [f"{name} is no secret" for name in sorted(SECRETS - set(secrets))]
    return findings


def converged_workspaces(**environment):
    """
    Args:
        environment: ``SEMAPHORE_WORKSPACES_VARIABLES`` and
            ``SEMAPHORE_WORKSPACES_SECRETS``.

    Returns:
        The ``workspaces`` entry of the spec the converge pipes into
        ``project.py`` while Workspaces is on.
    """
    task = load_yaml_str(read_text(str(SYNC)))[0]
    native = NativeEnvironment(undefined=StrictUndefined)
    handed = task["vars"]["semaphore_project_workspaces"]
    workspaces = {
        key: native.from_string(handed[key]).render(**environment)
        for key in ("variables", "secrets")
    }
    text = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    text.filters["bool"] = bool
    text.filters["combine"] = lambda left, right: {**left, **right}
    text.filters["to_json"] = json.dumps
    stdin = text.from_string(task["ansible.builtin.command"]["stdin"]).render(
        semaphore_project_spec={},
        semaphore_project_deploy={},
        semaphore_project_pool={},
        semaphore_project_workspaces=workspaces,
        SEMAPHORE_DEPLOY_ENABLED=False,
        SEMAPHORE_WORKSPACES_ENABLED=True,
        SEMAPHORE_POOL_ENABLED=False,
    )
    return json.loads(stdin)["workspaces"]


class TestWorkspacesEnvironment(unittest.TestCase):
    def setUp(self):
        self.vars = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
        self.variables = self.vars["SEMAPHORE_WORKSPACES_VARIABLES"]
        self.secrets = self.vars["SEMAPHORE_WORKSPACES_SECRETS"]

    def test_the_workspaces_environment_carries_what_members_and_user_need(self):
        self.assertEqual(environment_findings(self.variables, self.secrets), [])
        self.assertEqual(self.vars["SEMAPHORE_WORKSPACES_BAO_ROLE"], "members")

    def test_the_converge_hands_the_environment_to_the_workspaces_project(self):
        handed = {
            "variables": {"KC_URL": "https://auth.example"},
            "secrets": {"KC_CLIENT_SECRET": "client-secret"},
        }
        workspaces = converged_workspaces(
            SEMAPHORE_WORKSPACES_VARIABLES=handed["variables"],
            SEMAPHORE_WORKSPACES_SECRETS=handed["secrets"],
        )
        self.assertEqual(
            {key: workspaces[key] for key in ("variables", "secrets")}, handed
        )

    def test_negative_control_a_missing_variable_is_reported(self):
        variables = {k: v for k, v in self.variables.items() if k != "KC_URL"}
        self.assertEqual(
            environment_findings(variables, self.secrets), ["KC_URL is not set"]
        )

    def test_negative_control_a_plain_secret_is_reported(self):
        variables = {**self.variables, "SEMAPHORE_DB_PASS": "x"}
        secrets = {k: v for k, v in self.secrets.items() if k != "SEMAPHORE_DB_PASS"}
        self.assertEqual(
            environment_findings(variables, secrets),
            ["SEMAPHORE_DB_PASS is a plain variable", "SEMAPHORE_DB_PASS is no secret"],
        )


if __name__ == "__main__":
    unittest.main()
