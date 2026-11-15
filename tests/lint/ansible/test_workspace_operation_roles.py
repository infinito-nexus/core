from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

PLAYBOOK = PROJECT_ROOT / "playbook-workspace.yml"
REQUIREMENT = (
    PROJECT_ROOT / "docs" / "requirements" / "102-one-semaphore-runner-per-workspace.md"
)
OWNERS_SENTENCE = re.compile(r"Roles that own one: ([^\n]*?)\. `apply` is idempotent")
ROLE_NAME = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`")
LAST_ON_DESTROY = "web-app-keycloak"


def decided_owners():
    """Returns:
    The roles decision 3 of 102 names as owners of a per-workspace resource.
    """
    match = OWNERS_SENTENCE.search(read_text(str(REQUIREMENT)))
    assert match is not None, "102 decision 3 no longer names the owning roles"
    return sorted(ROLE_NAME.findall(match.group(1)))


def playbook_roles():
    """Returns:
    The apply order of the roles ``playbook-workspace.yml`` runs.
    """
    return load_yaml_str(read_text(str(PLAYBOOK)))[0]["vars"]["workspace_roles"]


def operation_findings(roles_dir, owners, order):
    """Args:
    roles_dir: the roles directory.
    owners: :func:`decided_owners`.
    order: :func:`playbook_roles`.

    Returns:
        Every role with ``tasks/workspace.yml`` outside the owners, and every
        difference between the owners and the playbook's roles.
    """
    held = sorted(
        p.parent.parent.name for p in Path(roles_dir).glob("*/tasks/workspace.yml")
    )
    findings = [
        f"{role} has tasks/workspace.yml but owns no workspace resource"
        for role in held
        if role not in owners
    ]
    if sorted(order) != owners:
        findings.append(
            f"playbook-workspace.yml runs {sorted(order)}, decision 3 names {owners}"
        )
    if order[:1] != [LAST_ON_DESTROY]:
        findings.append(
            f"{LAST_ON_DESTROY} must run first on apply, so destroy removes it last"
        )
    return findings


class TestWorkspaceOperationRoles(unittest.TestCase):
    def test_only_the_owning_roles_join_the_workspace_operation(self):
        self.assertEqual(
            operation_findings(
                PROJECT_ROOT / "roles", decided_owners(), playbook_roles()
            ),
            [],
        )

    def test_negative_control_a_foreign_workspace_task_is_reported(self):
        with tempfile.TemporaryDirectory() as roles:
            planted = Path(roles) / "web-app-wiki" / "tasks"
            planted.mkdir(parents=True)
            (planted / "workspace.yml").write_text("---\n", encoding="utf-8")
            self.assertEqual(
                operation_findings(roles, decided_owners(), playbook_roles()),
                ["web-app-wiki has tasks/workspace.yml but owns no workspace resource"],
            )

    def test_negative_control_a_missing_owner_in_the_playbook_is_reported(self):
        order = [role for role in playbook_roles() if role != "web-app-openbao"]
        self.assertEqual(
            len(operation_findings(PROJECT_ROOT / "roles", decided_owners(), order)), 1
        )

    def test_negative_control_keycloak_after_another_role_is_reported(self):
        order = playbook_roles()[1:] + playbook_roles()[:1]
        self.assertEqual(
            len(operation_findings(PROJECT_ROOT / "roles", decided_owners(), order)), 1
        )


if __name__ == "__main__":
    unittest.main()
