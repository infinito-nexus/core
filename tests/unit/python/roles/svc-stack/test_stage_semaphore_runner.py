from __future__ import annotations

import unittest

from tests.lint.ansible.roles.test_stack_batch_admission import (
    back_gate,
    back_reads,
    stage_sets,
)
from utils.cache.files import PROJECT_ROOT

from .test_stage_steps import CORE, STAGE, _includes

ROLE = "web-app-semaphore"
BRIDGE = "tasks/utils/stack.yml"
RUNNER = "utils/runner.yml"
PRUNE = "utils/runner/prune.yml"
RUNNER_REGISTERS = ("semaphore_runner_compose", "semaphore_runner_held")


class TestStageSemaphoreRunner(unittest.TestCase):
    def test_the_runner_is_staged_before_the_bridged_backend(self) -> None:
        self.assertTrue((PROJECT_ROOT / "roles" / ROLE / BRIDGE).is_file())
        self.assertIn(RUNNER, _includes(ROLE, STAGE))
        self.assertNotIn(RUNNER, _includes(ROLE, CORE))

    def test_the_prune_stays_after_the_backend(self) -> None:
        self.assertIn(PRUNE, _includes(ROLE, CORE))
        self.assertNotIn(PRUNE, _includes(ROLE, STAGE))

    def test_the_backend_reads_the_runner_the_stage_registers(self) -> None:
        reads, staged = back_reads(ROLE), stage_sets(ROLE)
        for name in RUNNER_REGISTERS:
            with self.subTest(name=name):
                self.assertIn(name, reads)
                self.assertIn(name, staged)
        self.assertEqual(back_gate([ROLE]), [])


if __name__ == "__main__":
    unittest.main()
