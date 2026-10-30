from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

WORKFLOW = PROJECT_ROOT / ".github/workflows/call-orchestrator.yml"
GATE = "test-deploy-chunk-1-gate"


class TestBatchOneGate(unittest.TestCase):
    def setUp(self) -> None:
        self.jobs = load_yaml_any(str(WORKFLOW))["jobs"]
        self.later = {
            int(name.rsplit("-", 1)[1]): body
            for name, body in self.jobs.items()
            if re.fullmatch(r"test-deploy-chunk-\d+", name)
            and int(name.rsplit("-", 1)[1]) >= 2
        }

    def test_the_gate_waits_for_batch_0_and_the_workspace_test(self) -> None:
        gate = self.jobs[GATE]
        self.assertEqual(set(gate["needs"]), {"test-deploy-chunk-0", "test-workspace"})
        self.assertIn("inputs.chunk_gate", gate["if"])
        self.assertIn("!cancelled()", gate["if"])

    def test_the_gate_fails_when_batch_0_or_the_workspace_test_failed(self) -> None:
        refusing = [
            step for step in self.jobs[GATE]["steps"] if "exit 1" in step.get("run", "")
        ]
        self.assertEqual(len(refusing), 1)
        condition = refusing[0]["if"]
        self.assertIn("needs.test-deploy-chunk-0.result", condition)
        self.assertIn("needs.test-workspace.result", condition)

    def test_batch_1_runs_after_a_green_gate_only_while_the_gate_is_on(self) -> None:
        batch = self.jobs["test-deploy-chunk-1"]
        self.assertIn(GATE, batch["needs"])
        self.assertRegex(
            batch["if"],
            re.compile(
                r"!inputs\.chunk_gate\s*\|\|.*needs\.test-deploy-chunk-1-gate\.result == 'success'",
                re.DOTALL,
            ),
        )

    def test_a_red_gate_stops_every_later_batch(self) -> None:
        self.assertTrue(self.later)
        for index, body in sorted(self.later.items()):
            with self.subTest(batch=index):
                self.assertIn(GATE, body["needs"])
                self.assertIn(
                    "needs.test-deploy-chunk-1-gate.result != 'failure'", body["if"]
                )

    def test_the_finish_job_needs_the_gate(self) -> None:
        self.assertIn(GATE, self.jobs["done"]["needs"])


if __name__ == "__main__":
    unittest.main()
