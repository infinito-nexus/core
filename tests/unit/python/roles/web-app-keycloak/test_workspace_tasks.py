from __future__ import annotations

import copy
import sys
import unittest
import unittest.mock as mock

import jinja2
from ansible.plugins.filter.core import FilterModule as CoreFilters
from ansible.plugins.test.core import TestModule as CoreTests

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))
sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python/workspace"))

import members as members_m
import organization as m
import workspaces as ws_m

from .files.workspace._workspace_fake import (
    CUSTOMER,
    MANAGED,
    OWNER,
    ROOT,
    SIGN_IN,
    STAFF,
    USERS,
    WORKSPACES_CLIENT,
    WS,
    FakeKeycloak,
    state,
)

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"


def members_env(action: str, **values: str) -> dict:
    """
    Args:
        action: MEMBERS_ACTION.
        **values: further task variables.

    Returns:
        The environment of one members task.
    """
    return {
        "WORKSPACE": WS,
        "MEMBERS_ACTION": action,
        "KC_RBAC_GROUP_ROOT": ROOT,
        "KC_SIGN_IN_GROUP": SIGN_IN,
        "MEMBERS_ROSTER_FILE": "/dev/null",
        **values,
    }


class TestRemoveProtections(unittest.TestCase):
    def setUp(self) -> None:
        self.kc = FakeKeycloak(USERS)
        m.apply(self.kc, WS, WORKSPACES_CLIENT)
        (self.org_id,) = self.kc.orgs
        ws = ws_m.Workspace.load(self.kc, WS, "add")
        members_m.add(self.kc, ws, {"WORKSPACE_MEMBER": OWNER}, lambda line: None)
        for user_id, kind in ((STAFF, "UNMANAGED"), (MANAGED, "MANAGED")):
            self.kc.memberships[self.org_id][user_id] = kind
        groups = {g["name"]: g["id"] for g in self.kc.org_groups[self.org_id].values()}
        self.kc.group_members[groups["Viewer"]] |= {STAFF, MANAGED}

    def test_remove_refuses_each_protected_member(self) -> None:
        for user_id, reason in ((MANAGED, "managed"), (STAFF, "platform_role")):
            with self.subTest(reason=reason):
                before = state(self.kc)
                self.kc.writes.clear()
                with mock.patch.object(
                    members_m, "service_account", lambda env: self.kc
                ):
                    for phase in ("prepare", "settle"):
                        with self.assertRaises(ws_m.RefusalError) as raised:
                            members_m.run(
                                phase,
                                members_env("remove", WORKSPACE_MEMBER=user_id),
                                print,
                            )
                        self.assertEqual(raised.exception.reason, reason)
                self.assertEqual(self.kc.writes, [])
                self.assertEqual(state(self.kc), before)

    def test_remove_of_an_unprotected_member_ends_the_membership(self) -> None:
        self.kc.memberships[self.org_id][CUSTOMER] = "UNMANAGED"
        with mock.patch.object(members_m, "service_account", lambda env: self.kc):
            for phase in ("prepare", "settle"):
                members_m.run(
                    phase, members_env("remove", WORKSPACE_MEMBER=CUSTOMER), print
                )
        self.assertNotIn(CUSTOMER, self.kc.memberships[self.org_id])
        self.assertIn(CUSTOMER, self.kc.users)


class TestWorkspaceTask(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = load_yaml_any(str(ROLE_DIR / "tasks/workspace.yml"))
        cls.steps = load_yaml_any(
            str(ROLE_DIR / "tasks/utils/workspace/organization.yml")
        )

    def test_the_task_refuses_while_organizations_are_off(self) -> None:
        guard = self.tasks[0]["ansible.builtin.assert"]
        self.assertEqual(guard["that"], "KEYCLOAK_ORGANIZATIONS_ENABLED | bool")

    def test_the_organization_step_runs_on_the_stack_host(self) -> None:
        include = self.tasks[1]
        self.assertEqual(
            include["ansible.builtin.include_tasks"], "utils/workspace/organization.yml"
        )
        self.assertEqual(include["when"], "IS_STACK_HOST | bool")

    def test_the_task_runs_the_organization_script_with_the_workspace_inputs(
        self,
    ) -> None:
        step = next(t for t in self.steps if "vars" in t)
        self.assertEqual(step["vars"]["rest_script"], "workspace/organization.py")
        self.assertEqual(
            step["vars"]["rest_script_env"],
            {
                "KC_WORKSPACES_CLIENT": "{{ KEYCLOAK_WORKSPACES_CLIENT_ID }}",
                "WORKSPACE": "{{ WORKSPACE }}",
                "WORKSPACE_ACTION": "{{ WORKSPACE_ACTION }}",
            },
        )
        self.assertTrue(
            (ROLE_DIR / "files/python" / step["vars"]["rest_script"]).is_file()
        )

    def test_the_task_fails_on_a_failed_organization_step(self) -> None:
        failing = next(t for t in self.steps if "ansible.builtin.fail" in t)
        self.assertEqual(failing["when"], "kc_workspace_organization.rc != 0")


def jinja() -> jinja2.Environment:
    """
    Returns:
        An environment with the Ansible core filters and tests.
    """
    environment = jinja2.Environment(  # noqa: S701 - renders an Ansible set_fact value, never HTML
        undefined=jinja2.StrictUndefined
    )
    environment.filters.update(CoreFilters().filters())
    environment.tests.update(CoreTests().tests())
    return environment


def handover_findings(
    steps: list[dict], stdout_lines: list[str], owner: str
) -> list[str]:
    """
    Args:
        steps: ``tasks/utils/workspace/organization.yml``, possibly planted.
        stdout_lines: what the organization script printed on apply.
        owner: the id of the ``Owner`` group the apply created.

    Returns:
        Why the steps do not hand that id, as ``workspace_owner_group``, to
        every host after a successful apply.
    """
    handing = [
        t
        for t in steps
        if "workspace_owner_group" in (t.get("ansible.builtin.set_fact") or {})
    ]
    if len(handing) != 1:
        return [f"{len(handing)} steps hand workspace_owner_group to the later roles"]
    (task,) = handing
    findings = []
    if task.get("delegate_facts") is not True or task.get("loop") != (
        "{{ ansible_play_hosts_all }}"
    ):
        findings.append("the Owner group id stays on the Keycloak host")
    if task.get("when") != "WORKSPACE_ACTION == 'apply'":
        findings.append(f"the hand-over runs when {task.get('when')}")
    failing = next(i for i, t in enumerate(steps) if "ansible.builtin.fail" in t)
    if steps.index(task) < failing:
        findings.append("the hand-over runs before the failure check")
    value = (
        jinja()
        .from_string(task["ansible.builtin.set_fact"]["workspace_owner_group"])
        .render(kc_workspace_organization={"stdout_lines": stdout_lines})
        .strip()
    )
    if value != owner:
        findings.append(f"the hand-over yields {value!r}")
    return findings


class TestOwnerHandover(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.steps = load_yaml_any(
            str(ROLE_DIR / "tasks/utils/workspace/organization.yml")
        )

    def setUp(self) -> None:
        self.kc = FakeKeycloak(USERS)
        lines = m.apply(self.kc, WS, WORKSPACES_CLIENT)
        self.owner = m.owner_group(self.kc, WS)
        self.stdout = [*lines, f"{m.OWNER_LINE} {self.owner}", "summary created=16"]

    def test_apply_hands_the_owner_group_id_to_every_host(self) -> None:
        self.assertEqual(handover_findings(self.steps, self.stdout, self.owner), [])

    def test_the_openbao_pin_reads_the_fact_keycloak_hands_over(self) -> None:
        pin = read_text(
            str(PROJECT_ROOT / "roles/web-app-openbao/tasks/workspace/apply.yml")
        )
        self.assertIn("workspace_owner_group | quote", pin)
        order = load_yaml_any(str(PROJECT_ROOT / "playbook-workspace.yml"))[0]["vars"][
            "workspace_roles"
        ]
        self.assertLess(order.index("web-app-keycloak"), order.index("web-app-openbao"))

    def test_negative_control_steps_without_the_hand_over_are_reported(self) -> None:
        planted = [
            t
            for t in copy.deepcopy(self.steps)
            if "workspace_owner_group" not in (t.get("ansible.builtin.set_fact") or {})
        ]
        self.assertEqual(
            handover_findings(planted, self.stdout, self.owner),
            ["0 steps hand workspace_owner_group to the later roles"],
        )

    def test_negative_control_a_hand_over_on_one_host_is_reported(self) -> None:
        planted = copy.deepcopy(self.steps)
        task = next(
            t
            for t in planted
            if "workspace_owner_group" in (t.get("ansible.builtin.set_fact") or {})
        )
        del task["delegate_facts"]
        self.assertEqual(
            handover_findings(planted, self.stdout, self.owner),
            ["the Owner group id stays on the Keycloak host"],
        )

    def test_negative_control_another_group_id_is_reported(self) -> None:
        viewer = next(
            g["id"]
            for groups in self.kc.org_groups.values()
            for g in groups.values()
            if g["name"] == "Viewer"
        )
        self.assertEqual(
            handover_findings(self.steps, self.stdout, viewer),
            [f"the hand-over yields {self.owner!r}"],
        )


if __name__ == "__main__":
    unittest.main()
