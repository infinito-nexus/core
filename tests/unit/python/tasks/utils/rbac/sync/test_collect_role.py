from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.templating.ansible import _trust_as_template

TASKS = PROJECT_ROOT / "tasks/utils/rbac/sync/collect_role.yml"
HOOK = "web-app-erpnext"
MAPPED_GROUP = "/roles/web-app-consumer/auditor"
TENANT_GROUP = "/roles/web-app-consumer/t.example/auditor"


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(TASKS), trusted_as_template=True)


def _index(predicate) -> int:
    return next(index for index, task in enumerate(_tasks()) if predicate(task))


def _render(expression: str, role: str):
    templar = Templar(
        loader=DataLoader(),
        variables={"rbac_sync_role": role, "rbac_sync_application_id": HOOK},
    )
    return templar.template(_trust_as_template(expression))


def _check():
    return _tasks()[_index(lambda task: "ansible.builtin.assert" in task)]


def _members_vars():
    return _tasks()[_index(lambda task: "members.yml" in str(task))]["vars"]


def _group(role: str) -> tuple[str, str]:
    members = _members_vars()
    return (
        _render(members["rbac_members_application_id"], role),
        _render(members["rbac_members_role"], role),
    )


def _passes(role: str) -> bool:
    check = _check()
    if not _render("{{ " + check["when"] + " }}", role):
        return True
    return all(
        _render("{{ " + condition + " }}", role)
        for condition in check["ansible.builtin.assert"]["that"]
    )


class TestCollectRole(unittest.TestCase):
    def test_a_role_name_is_a_role_of_the_hooks_application(self) -> None:
        self.assertEqual(_group("manager"), (HOOK, "manager"))
        self.assertTrue(_passes("manager"))

    def test_a_group_path_names_a_role_of_another_application(self) -> None:
        for path in (MAPPED_GROUP, "roles/web-app-consumer/auditor/"):
            with self.subTest(path=path):
                self.assertEqual(_group(path), ("web-app-consumer", "auditor"))
                self.assertTrue(_passes(path))

    def test_a_path_of_another_shape_fails_the_check(self) -> None:
        for path in (TENANT_GROUP, "/roles/web-app-consumer"):
            with self.subTest(path=path):
                self.assertFalse(_passes(path))

    def test_the_check_runs_before_the_member_lookup(self) -> None:
        self.assertEqual(
            _group(TENANT_GROUP),
            ("web-app-consumer", "auditor"),
            "the parse alone reads a tenant path as the tenant-less group",
        )
        self.assertLess(
            _index(lambda task: "ansible.builtin.assert" in task),
            _index(lambda task: "members.yml" in str(task)),
        )


if __name__ == "__main__":
    unittest.main()
