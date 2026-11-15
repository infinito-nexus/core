from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
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


class TestWorkspacesEnvironment(unittest.TestCase):
    def setUp(self):
        self.vars = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
        self.variables = self.vars["SEMAPHORE_WORKSPACES_VARIABLES"]
        self.secrets = self.vars["SEMAPHORE_WORKSPACES_SECRETS"]

    def test_the_workspaces_environment_carries_what_members_and_user_need(self):
        self.assertEqual(environment_findings(self.variables, self.secrets), [])
        self.assertEqual(self.vars["SEMAPHORE_WORKSPACES_BAO_ROLE"], "members")

    def test_the_converge_hands_the_environment_to_the_workspaces_project(self):
        converge = read_text(str(ROLE / "tasks" / "utils" / "project" / "sync.yml"))
        self.assertIn('variables: "{{ SEMAPHORE_WORKSPACES_VARIABLES }}"', converge)
        self.assertIn('secrets: "{{ SEMAPHORE_WORKSPACES_SECRETS }}"', converge)

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
