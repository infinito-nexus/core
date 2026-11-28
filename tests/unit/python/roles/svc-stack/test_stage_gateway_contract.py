from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT

from .test_stage_steps import CORE, STAGE, _includes, _tasks

BRIDGE = "tasks/utils/stack.yml"
CONTRACT = "roles/svc-ai-litellm/tasks/utils/consumer_contract.yml"
RENDER = "roles/sys-svc-compose/tasks/utils/render_replicated_templates.yml"
STAGED = {
    "web-app-flowise": (CONTRACT, RENDER),
    "web-app-worldmonitor": (CONTRACT,),
}


class TestStageGatewayContract(unittest.TestCase):
    def test_each_role_runs_its_steps_before_its_bridged_backend(self) -> None:  # nocheck: test.text-presence -- asserts on the include targets of the parsed stage and core task files  # fmt: skip
        for role, steps in STAGED.items():
            for step in steps:
                with self.subTest(role=role, step=step):
                    self.assertTrue((PROJECT_ROOT / "roles" / role / BRIDGE).is_file())
                    self.assertIn(step, _includes(role, STAGE))
                    self.assertNotIn(step, _includes(role, CORE))

    def test_each_stage_checks_the_contract_before_it_stages(self) -> None:
        for role, steps in STAGED.items():
            with self.subTest(role=role):
                tasks = _tasks(role, STAGE)
                self.assertEqual(len(tasks), len(steps))
                first = str(tasks[0].get("ansible.builtin.include_tasks"))
                self.assertIn(CONTRACT, first)


if __name__ == "__main__":
    unittest.main()
