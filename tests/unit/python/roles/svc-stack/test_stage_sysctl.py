from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

from .test_stage_steps import STAGE, _includes, _tasks

BRIDGE = "tasks/utils/stack.yml"
SYSCTL = "sys-sysctl"
RENDER = "roles/sys-svc-compose/tasks/utils/render_replicated_templates.yml"
STAGED = {
    "web-app-magento": ("tasks/00_core.yml", (RENDER,)),
    "web-app-shopware": (ROLE_FILE_TASKS_MAIN, ()),
}


def _sysctl_tasks(role: str, rel: str) -> list[dict]:
    return [
        task
        for task in _tasks(role, rel)
        if (task.get("ansible.builtin.include_role") or {}).get("name") == SYSCTL
    ]


class TestStageSysctl(unittest.TestCase):
    def test_each_role_raises_its_sysctl_before_its_bridged_backend(self) -> None:
        for role, (core, _renders) in STAGED.items():
            with self.subTest(role=role):
                self.assertTrue((PROJECT_ROOT / "roles" / role / BRIDGE).is_file())
                self.assertEqual(len(_sysctl_tasks(role, STAGE)), 1)
                self.assertEqual(_sysctl_tasks(role, core), [])
                self.assertEqual(_tasks(role, STAGE)[0], _sysctl_tasks(role, STAGE)[0])

    def test_each_stage_renders_the_config_the_backend_mounts(self) -> None:
        for role, (core, renders) in STAGED.items():
            with self.subTest(role=role):
                self.assertEqual(len(_tasks(role, STAGE)), 1 + len(renders))
                for render in renders:
                    self.assertIn(render, _includes(role, STAGE))
                    self.assertNotIn(render, _includes(role, core))


if __name__ == "__main__":
    unittest.main()
