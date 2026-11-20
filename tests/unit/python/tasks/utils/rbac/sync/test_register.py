from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "tasks/utils/rbac/sync/register.yml"


def _written_names() -> list[str]:
    tasks = DataLoader().load_from_file(str(TASKS), trusted_as_template=True)
    copy = next(task for task in tasks if "ansible.builtin.copy" in task)
    variables = {
        "rbac_sync_script_name": "main.py",
        "rbac_sync_script": "print('hook')",
        "rbac_sync_modules": [{"name": "helper.py", "content": ""}],
        "rbac_sync_hook": {"application_id": "web-app-example"},
    }
    templar = Templar(loader=DataLoader(), variables=variables)
    return [item["name"] for item in templar.template(_trust_as_template(copy["loop"]))]


class TestTheHookDefinitionComesFirst(unittest.TestCase):
    def test_hook_json_is_written_before_the_script_and_its_modules(self) -> None:
        self.assertEqual(_written_names(), ["hook.json", "main.py", "helper.py"])


if __name__ == "__main__":
    unittest.main()
