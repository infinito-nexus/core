from __future__ import annotations

import unittest
from itertools import product

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

RECORDS = ("community.general.ldap_search", "ansible.builtin.set_fact")
CARRIERS = {
    "tasks/utils/rbac/members.yml": ("rbac_members_attributes", RECORDS),
    "tasks/utils/rbac/users.yml": ("rbac_users_attributes", RECORDS),
    "tasks/utils/rbac/sync/collect_role.yml": ("rbac_sync_attributes", RECORDS),
    "tasks/utils/rbac/sync/register.yml": (
        "rbac_sync_attributes",
        ("ansible.builtin.command",),
    ),
}


def _carrying_tasks(rel: str, modules: tuple[str, ...]) -> list[dict]:
    return [
        task
        for task in load_yaml_str(read_text(str(PROJECT_ROOT / rel)))
        if any(key in task for key in modules)
    ]


def _masked(task: dict, parameter: str, mask: bool, attributes: list[str]) -> bool:
    templar = Templar(
        loader=DataLoader(),
        variables={"MASK_CREDENTIALS_IN_LOGS": mask, parameter: attributes},
    )
    return templar.template(_trust_as_template(task["no_log"]))


class TestMemberRecordsWithAttributesStayOutOfTheLog(unittest.TestCase):
    def test_every_task_that_carries_members_is_masked_by_its_attributes(self) -> None:
        for rel, (parameter, modules) in CARRIERS.items():
            tasks = _carrying_tasks(rel, modules)
            self.assertTrue(tasks, rel)
            for task, (mask, attributes) in product(
                tasks, product((True, False), ([], ["street"]))
            ):
                with self.subTest(
                    file=rel, task=task["name"], mask=mask, attributes=attributes
                ):
                    self.assertIn("no_log", task)
                    self.assertIs(
                        _masked(task, parameter, mask, attributes),
                        mask or bool(attributes),
                    )


if __name__ == "__main__":
    unittest.main()
